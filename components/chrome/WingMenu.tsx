"use client"

import React, { useEffect, useRef } from "react"
import { useEscape } from "@/components/chat/header/useEscape"

export interface WingMenuItem {
  /** Stable key. */
  id: string
  label: string
  /** Tooltip of the item; the label when absent. */
  title?: string
  /** The icon cell: an icon component or a character. */
  glyph: React.ReactNode
  /** The key text at the right edge ("Esc", an unread count). */
  hint?: React.ReactNode
  /** A dot at the item: something here needs a look (unread alerts). */
  dot?: boolean
  run: () => void | Promise<void>
}

export interface WingMenuProps {
  open: boolean
  onToggle: () => void
  onClose: () => void
  /** Small heading at the top of the menu ("Chat", "Dashboard"). */
  heading: string
  /** Accessible name of the menu. */
  ariaLabel: string
  items: WingMenuItem[]
  /** Colour of the dots. */
  dotColor?: string
  /** Extra class on the ◉ button ("touch" for the phone layout). */
  buttonClass?: string
}

/**
 * The ◉ menu: ONE component for both wings (concept iris-dashboard.html). The
 * ◉ button goes in the wing header row; the menu opens under the header, so the
 * header must be a positioned box. A dot shows on the button while any item has one.
 * Esc closes the menu and goes no further (the wing's own Esc handler stays quiet).
 */
export function WingMenu({ open, onToggle, onClose, heading, ariaLabel, items, dotColor, buttonClass = "" }: WingMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)
  useEscape(open, onClose)

  // A click outside the menu closes it (the ◉ button toggles on its own).
  useEffect(() => {
    if (!open) return
    const h = (e: MouseEvent) => {
      const t = e.target as Element
      if (!menuRef.current?.contains(t) && !t.closest?.("[data-menu-button]")) onClose()
    }
    document.addEventListener("mousedown", h)
    return () => document.removeEventListener("mousedown", h)
  }, [open, onClose])

  const unread = items.some((i) => i.dot)

  return (
    <>
      <button
        type="button"
        className={`iris-hd-iconbtn${buttonClass ? ` ${buttonClass}` : ""}`}
        data-menu-button="true"
        title="More"
        aria-label="More"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={onToggle}
      >
        ◉
        {unread && <i className="iris-hd-act" role="img" aria-label="Unread alerts" style={{ background: dotColor, animation: "none" }} />}
      </button>

      {open && (
        <div
          ref={menuRef}
          className="iris-hd-menu"
          data-wing-menu={heading}
          role="menu"
          aria-label={ariaLabel}
          // The header around it is a window drag handle; a press in the menu is not a drag.
          onMouseDown={(e) => e.stopPropagation()}
        >
          <div className="iris-mh">{heading}</div>
          {items.map((it) => (
            <button
              key={it.id}
              type="button"
              role="menuitem"
              title={it.title ?? it.label}
              onClick={() => { onClose(); void it.run() }}
            >
              <span className="g">{it.glyph}</span>
              {it.label}
              {it.dot && <i className="iris-mdot" aria-hidden="true" style={{ background: dotColor }} />}
              {it.hint ? <span className="k">{it.hint}</span> : null}
            </button>
          ))}
        </div>
      )}
    </>
  )
}
