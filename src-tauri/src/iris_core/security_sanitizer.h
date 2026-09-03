#ifndef SECURITY_SANITIZER_H
#define SECURITY_SANITIZER_H

#include <string>
#include <vector>
#include <utility>

// RE2 forward declaration
namespace re2 {
    class RE2;
}

// ============================================================================
// SecuritySanitizer — Zero-Trust Payload Scrubber (Phase 3)
// Uses Google RE2 for guaranteed linear-time matching (O(n)), eliminating
// all ReDoS risk. No hard cap before scan — full payload is sanitized,
// then truncated to MAX_STORED_BYTES if needed.
// ============================================================================

class SecuritySanitizer {
public:
    static constexpr size_t MAX_STORED_BYTES = 65536;

    static SecuritySanitizer& get_instance();

    SecuritySanitizer(const SecuritySanitizer&) = delete;
    SecuritySanitizer& operator=(const SecuritySanitizer&) = delete;

    /**
     * Sanitize a payload: scrub secrets from full content, then truncate
     * the stored result to MAX_STORED_BYTES if it exceeds the limit.
     * @param payload   Raw input payload.
     * @return Pair of (scrubbed string, bool indicating if any rule matched).
     */
    std::pair<std::string, bool> sanitize_payload(const std::string& payload);

private:
    SecuritySanitizer();
    ~SecuritySanitizer();

    struct Rule {
        re2::RE2* regex;
        std::string replacement;
    };

    std::vector<Rule> rules_;
};

#endif // SECURITY_SANITIZER_H
