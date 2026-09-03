/*
 * IrisAudioPlayer — lock-free ring-buffer audio playback via PortAudio + pybind11
 *
 * Designed for low-latency TTS output on Windows with WASAPI exclusive mode.
 */

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>

#include <atomic>
#include <condition_variable>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

// PortAudio is shipped inside the sounddevice wheel; we locate headers at build time.
#include <portaudio.h>

namespace py = pybind11;

class IrisAudioPlayer {
public:
    static constexpr size_t RING_SIZE = 24000 * 10; // 10 seconds @ 24kHz float32

private:
    std::vector<float> ring_;
    std::atomic<size_t> write_pos_{0};
    std::atomic<size_t> read_pos_{0};
    std::atomic<bool> interrupted_{false};
    std::atomic<bool> running_{false};
    PaStream* stream_{nullptr};
    int sample_rate_{24000};
    std::mutex mtx_;
    std::condition_variable cv_;

    size_t ring_mask() const { return ring_.size() - 1; }

    size_t available_to_read() const {
        const size_t w = write_pos_.load(std::memory_order_acquire);
        const size_t r = read_pos_.load(std::memory_order_acquire);
        return (w >= r) ? (w - r) : (ring_.size() - (r - w));
    }

    size_t available_to_write() const {
        return ring_.size() - 1 - available_to_read();
    }

public:
    IrisAudioPlayer() : ring_(RING_SIZE) {}

    ~IrisAudioPlayer() { close(); }

    bool open(int device_index, int sample_rate) {
        if (running_.load()) return true;
        sample_rate_ = sample_rate;

        PaError err = Pa_Initialize();
        if (err != paNoError) {
            // PortAudio uses ref-counting: multiple Pa_Initialize calls are safe.
            // If sounddevice already initialized it, Pa_Initialize just bumps the ref count.
        }

        PaStreamParameters outParams;
        std::memset(&outParams, 0, sizeof(outParams));
        outParams.device = (device_index < 0)
                               ? Pa_GetDefaultOutputDevice()
                               : device_index;
        outParams.channelCount = 1;
        outParams.sampleFormat = paFloat32;
        outParams.suggestedLatency = 0.005; // 5 ms — low latency

        err = Pa_OpenStream(
            &stream_,
            nullptr,        // no input
            &outParams,
            sample_rate_,
            paFramesPerBufferUnspecified,
            paClipOff,
            &IrisAudioPlayer::pa_callback_static,
            this
        );
        if (err != paNoError) {
            return false;
        }

        err = Pa_StartStream(stream_);
        if (err != paNoError) {
            Pa_CloseStream(stream_);
            stream_ = nullptr;
            return false;
        }

        running_.store(true);
        interrupted_.store(false);
        return true;
    }

    void push_chunk(py::array_t<float> chunk) {
        if (!running_.load()) return;
        if (interrupted_.load()) return;

        py::buffer_info info = chunk.request();
        const size_t n = info.size;
        const float* src = static_cast<const float*>(info.ptr);

        std::unique_lock<std::mutex> lock(mtx_);
        // Wait until there's space (with timeout to avoid deadlock)
        cv_.wait_for(lock, std::chrono::milliseconds(50), [this, n] {
            return available_to_write() >= n || interrupted_.load();
        });

        if (interrupted_.load()) return;

        const size_t mask = ring_mask();
        size_t w = write_pos_.load(std::memory_order_relaxed);
        for (size_t i = 0; i < n; ++i) {
            ring_[w & mask] = src[i];
            ++w;
        }
        write_pos_.store(w, std::memory_order_release);
        cv_.notify_one();
    }

    void interrupt() {
        interrupted_.store(true);
        cv_.notify_all();
    }

    void wait_done() {
        if (!running_.load()) return;
        // Wait until ring is empty and no more data expected
        while (available_to_read() > 0 && !interrupted_.load()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
    }

    void close() {
        if (!running_.load()) return;
        running_.store(false);
        interrupted_.store(true);
        cv_.notify_all();

        if (stream_) {
            Pa_StopStream(stream_);
            Pa_CloseStream(stream_);
            stream_ = nullptr;
        }
    }

    size_t pending_samples() const {
        return available_to_read();
    }

private:
    static int pa_callback_static(
        const void* input,
        void* output,
        unsigned long frameCount,
        const PaStreamCallbackTimeInfo* timeInfo,
        PaStreamCallbackFlags statusFlags,
        void* userData
    ) {
        return static_cast<IrisAudioPlayer*>(userData)->pa_callback(
            output, frameCount);
    }

    int pa_callback(void* output, unsigned long frameCount) {
        float* out = static_cast<float*>(output);

        if (interrupted_.load()) {
            std::memset(out, 0, frameCount * sizeof(float));
            return paComplete;
        }

        const size_t mask = ring_mask();
        size_t r = read_pos_.load(std::memory_order_relaxed);
        size_t to_read = available_to_read();
        size_t n = std::min<size_t>(to_read, frameCount);

        for (size_t i = 0; i < n; ++i) {
            out[i] = ring_[r & mask];
            ++r;
        }
        read_pos_.store(r, std::memory_order_release);

        // Fill remainder with silence (zero)
        if (n < frameCount) {
            std::memset(out + n, 0, (frameCount - n) * sizeof(float));
        }

        cv_.notify_one();
        return paContinue;
    }
};

PYBIND11_MODULE(iris_audio, m) {
    m.doc() = "Iris native audio playback — low-latency ring buffer via PortAudio";
    py::class_<IrisAudioPlayer>(m, "IrisAudioPlayer")
        .def(py::init<>())
        .def("open", &IrisAudioPlayer::open,
             py::arg("device_index") = -1,
             py::arg("sample_rate") = 24000,
             "Open a PortAudio output stream. device_index=-1 uses default.")
        .def("push_chunk", &IrisAudioPlayer::push_chunk,
             py::arg("chunk"),
             "Push a float32 numpy array into the ring buffer.")
        .def("interrupt", &IrisAudioPlayer::interrupt,
             "Signal the callback to drain and stop.")
        .def("wait_done", &IrisAudioPlayer::wait_done,
             "Block until the ring buffer is empty.")
        .def("close", &IrisAudioPlayer::close,
             "Close the stream and release resources.")
        .def("pending_samples", &IrisAudioPlayer::pending_samples,
             "Return the number of unread samples in the ring buffer.");
}
