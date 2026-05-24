'use client'

import React, { useMemo, useState } from 'react'

interface MindMapNode {
  id: string
  label: string
  level: number // 0 = H1 root, 1 = H2 parent, 2 = H3 leaf
  children: MindMapNode[]
  color?: string
  linkedFiles?: string[]
  collapsed?: boolean
}

interface MindMapViewProps {
  markdown: string
  onNodeClick?: (node: MindMapNode) => void
  onNodeContextMenu?: (node: MindMapNode, e: React.MouseEvent) => void
}

const BRANCH_COLORS = ['#60a5fa', '#34d399', '#fbbf24', '#f87171', '#a78bfa', '#22d3ee']

function parseMarkdownToTree(md: string): MindMapNode {
  const lines = md.split('\n')
  const root: MindMapNode = { id: 'root', label: 'Document', level: -1, children: [] }
  const stack: MindMapNode[] = [root]

  lines.forEach((line, idx) => {
    const headingMatch = line.match(/^(#{1,3})\s+(.+)$/)
    if (!headingMatch) return

    const level = headingMatch[1].length // 1, 2, or 3
    const label = headingMatch[2].trim()
    const node: MindMapNode = {
      id: `node-${idx}`,
      label,
      level: level - 1, // 0=H1, 1=H2, 2=H3
      children: [],
      color: BRANCH_COLORS[(level - 1) % BRANCH_COLORS.length],
    }

    // Pop stack to find correct parent
    while (stack.length > 1 && stack[stack.length - 1].level >= node.level) {
      stack.pop()
    }
    stack[stack.length - 1].children.push(node)
    stack.push(node)
  })

  return root.children[0] || root
}

function NodeRenderer({
  node,
  x,
  y,
  onClick,
  onContextMenu,
  collapsedNodes,
  toggleCollapse,
}: {
  node: MindMapNode
  x: number
  y: number
  onClick?: (n: MindMapNode) => void
  onContextMenu?: (n: MindMapNode, e: React.MouseEvent) => void
  collapsedNodes: Set<string>
  toggleCollapse: (id: string) => void
}) {
  const isCollapsed = collapsedNodes.has(node.id)
  const hasChildren = node.children.length > 0
  const nodeWidth = node.label.length * 7 + 24
  const nodeHeight = 26
  const color = node.color || '#60a5fa'
  const lighterColor = `${color}60`

  return (
    <g transform={`translate(${x},${y})`}>
      {/* Node rect */}
      <rect
        x={-nodeWidth / 2}
        y={-nodeHeight / 2}
        width={nodeWidth}
        height={nodeHeight}
        rx={6}
        fill={`${color}12`}
        stroke={color}
        strokeWidth={1}
        style={{ cursor: onClick ? 'pointer' : 'default' }}
        onClick={(e) => {
          e.stopPropagation()
          if (hasChildren) toggleCollapse(node.id)
          onClick?.(node)
        }}
        onContextMenu={(e) => {
          e.preventDefault()
          onContextMenu?.(node, e as unknown as React.MouseEvent)
        }}
      />
      {/* Label */}
      <text
        y={4}
        textAnchor="middle"
        fill="rgba(255,255,255,0.85)"
        fontSize={10}
        fontWeight={node.level === 0 ? 600 : 400}
      >
        {node.label}
      </text>
      {/* Collapse indicator */}
      {hasChildren && (
        <text x={nodeWidth / 2 - 4} y={4} fill={color} fontSize={8} textAnchor="middle">
          {isCollapsed ? '+' : '−'}
        </text>
      )}
      {/* Children */}
      {!isCollapsed && hasChildren && (
        <>
          {node.children.map((child, i) => {
            const childX = 0
            const childY = 60 + i * 50
            return (
              <g key={child.id}>
                {/* Edge line */}
                <line
                  x1={0}
                  y1={nodeHeight / 2}
                  x2={childX}
                  y2={childY - nodeHeight / 2}
                  stroke={lighterColor}
                  strokeWidth={1}
                />
                <NodeRenderer
                  node={child}
                  x={childX}
                  y={childY}
                  onClick={onClick}
                  onContextMenu={onContextMenu}
                  collapsedNodes={collapsedNodes}
                  toggleCollapse={toggleCollapse}
                />
              </g>
            )
          })}
        </>
      )}
    </g>
  )
}

export function MindMapView({ markdown, onNodeClick, onNodeContextMenu }: MindMapViewProps) {
  const [collapsedNodes, setCollapsedNodes] = useState<Set<string>>(new Set())

  const tree = useMemo(() => parseMarkdownToTree(markdown), [markdown])

  const toggleCollapse = (id: string) => {
    setCollapsedNodes((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="h-full overflow-auto">
      <svg width="100%" height="400" viewBox="-200 -30 400 460" style={{ minHeight: 400 }}>
        <NodeRenderer
          node={tree}
          x={0}
          y={20}
          onClick={onNodeClick}
          onContextMenu={onNodeContextMenu}
          collapsedNodes={collapsedNodes}
          toggleCollapse={toggleCollapse}
        />
      </svg>
    </div>
  )
}
