import "@testing-library/jest-dom"
import { render, screen, fireEvent } from "@testing-library/react"
import TaskListCard from "@/components/chat/TaskListCard"

jest.mock("framer-motion", () => {
  const React = require("react")
  const motion = new Proxy(
    {},
    {
      get: (_t: unknown, tag: string) =>
        React.forwardRef((props: Record<string, unknown>, ref: unknown) => {
          const { children, ...rest } = props || {}
          return React.createElement(tag, { ...rest, ref }, children)
        }),
    }
  )
  return {
    motion,
    AnimatePresence: ({ children }: { children: React.ReactNode }) =>
      React.createElement(React.Fragment, null, children),
  }
})

jest.mock("@/contexts/BrandColorContext", () => ({
  useBrandColor: () => ({
    getThemeConfig: () => ({
      glow: { color: "#00c8ff" },
      shimmer: { primary: "#00c8ff" },
      glass: { blur: 20, opacity: 0.18 },
    }),
  }),
}))

const steps = [
  { id: "s1", description: "Read the file", status: "done", toolName: "file_read" },
  { id: "s2", description: "Write the file", status: "working", toolName: "file_write" },
  { id: "s3", description: "Commit", status: "pending", toolName: "git_commit" },
]

describe("TaskListCard", () => {
  it("renders all steps when not collapsed", () => {
    render(<TaskListCard steps={steps} />)
    expect(screen.getByText("Read the file")).toBeInTheDocument()
    expect(screen.getByText("Write the file")).toBeInTheDocument()
    expect(screen.getByText("Commit")).toBeInTheDocument()
  })

  it("shows progress count done/total", () => {
    render(<TaskListCard steps={steps} />)
    expect(screen.getByText("1/3")).toBeInTheDocument()
  })

  it("collapses by default when many steps", () => {
    const many = Array.from({ length: 6 }, (_, i) => ({
      id: `s${i}`,
      description: `Step ${i}`,
      status: "pending",
    }))
    render(<TaskListCard steps={many} defaultCollapsed />)
    expect(screen.queryByText("Step 0")).not.toBeInTheDocument()
  })

  it("expands on toggle click", () => {
    const many = Array.from({ length: 6 }, (_, i) => ({
      id: `s${i}`,
      description: `Step ${i}`,
      status: "pending",
    }))
    render(<TaskListCard steps={many} defaultCollapsed />)
    fireEvent.click(screen.getByLabelText(/expand plan/i))
    expect(screen.getByText("Step 0")).toBeInTheDocument()
  })
})