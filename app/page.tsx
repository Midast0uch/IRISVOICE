import HexagonalControlCenter from "@/components/hexagonal-control-center"

export default function Home() {
  return (
    <main className="bg-transparent w-full min-h-screen flex items-center justify-center">
      <div style={{ width: 460, height: 460 }}>
        <HexagonalControlCenter />
      </div>
    </main>
  )
}
