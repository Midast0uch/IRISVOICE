"use client"

import React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"

interface NavLinkProps {
  to: string
  end?: boolean
  className?: string
  activeClassName?: string
  "aria-label"?: string
  children?: React.ReactNode
}

export function NavLink({ to, end, className, activeClassName, "aria-label": ariaLabel, children }: NavLinkProps) {
  const pathname = usePathname()
  const isActive = end ? pathname === to : pathname?.startsWith(to) || false
  const mergedClassName = `${className || ""} ${isActive ? activeClassName || "" : ""}`

  return (
    <Link
      href={to}
      className={mergedClassName}
      aria-label={ariaLabel}
    >
      {children}
    </Link>
  )
}
