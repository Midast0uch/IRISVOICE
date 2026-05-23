declare module '@dnd-kit/core' {
  import * as React from 'react'

  export interface DndContextProps {
    children: React.ReactNode
    onDragStart?(event: DragStartEvent): void
    onDragEnd?(event: DragEndEvent): void
    onDragOver?(event: DragOverEvent): void
    [key: string]: any
  }

  export interface DragStartEvent {
    active: Active
  }

  export interface DragEndEvent {
    active: Active
    over: Over | null
  }

  export interface DragOverEvent {
    active: Active
    over: Over | null
  }

  export interface Active {
    id: string | number
    data: DataRef
    rect: LayoutRect
    [key: string]: any
  }

  export interface Over {
    id: string | number
    rect: LayoutRect
    data: DataRef
    disabled: boolean
    [key: string]: any
  }

  export interface DataRef {
    current: Record<string, any>
  }

  export interface LayoutRect {
    width: number
    height: number
    offsetLeft: number
    offsetTop: number
  }

  export interface UseDraggableReturn {
    attributes: DraggableAttributes
    listeners: DraggableSyntheticListeners
    setNodeRef: (node: HTMLElement | null) => void
    transform: { x: number; y: number } | null
    isDragging: boolean
    active: Active | null
    [key: string]: any
  }

  export interface DraggableAttributes {
    role: string
    tabIndex: number
    'aria-disabled': boolean
    'aria-pressed'?: boolean
    'aria-roledescription': string
    [key: string]: any
  }

  export type DraggableSyntheticListeners = Record<string, (event: any) => void> | undefined

  export interface UseDroppableReturn {
    setNodeRef: (node: HTMLElement | null) => void
    isOver: boolean
    over: Over | null
    active: Active | null
    [key: string]: any
  }

  export interface UseDraggableArguments {
    id: string | number
    data?: Record<string, any>
    disabled?: boolean
    [key: string]: any
  }

  export interface UseDroppableArguments {
    id: string | number
    disabled?: boolean
    data?: Record<string, any>
    [key: string]: any
  }

  export const DndContext: React.FC<DndContextProps>

  export function useDraggable(args: UseDraggableArguments): UseDraggableReturn
  export function useDroppable(args: UseDroppableArguments): UseDroppableReturn
}
