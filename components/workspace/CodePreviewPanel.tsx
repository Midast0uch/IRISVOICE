'use client'

import { Highlight, themes } from 'prism-react-renderer'

interface CodePreviewPanelProps {
  code: string
  language?: string
  showLineNumbers?: boolean
}

export function CodePreviewPanel({ code, language = 'tsx', showLineNumbers = true }: CodePreviewPanelProps) {
  return (
    <div className="h-full overflow-auto text-[10px] leading-4 font-mono">
      <Highlight theme={themes.vsDark} code={code.trim()} language={language}>
        {({ className, style, tokens, getLineProps, getTokenProps }) => (
          <pre className={className} style={{ ...style, margin: 0, padding: '6px 8px', background: 'transparent' }}>
            {tokens.map((line, i) => (
              <div key={i} {...getLineProps({ line })} className="table-row">
                {showLineNumbers && (
                  <span className="table-cell text-right pr-3 select-none" style={{ color: 'rgba(255,255,255,0.15)', minWidth: '1.5em' }}>
                    {i + 1}
                  </span>
                )}
                <span className="table-cell">
                  {line.map((token, key) => (
                    <span key={key} {...getTokenProps({ token })} />
                  ))}
                </span>
              </div>
            ))}
          </pre>
        )}
      </Highlight>
    </div>
  )
}
