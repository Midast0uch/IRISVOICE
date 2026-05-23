declare module '@xterm/xterm' {
  export interface ITerminalOptions {
    cols?: number
    rows?: number
    cursorBlink?: boolean
    cursorStyle?: 'block' | 'underline' | 'bar'
    fontFamily?: string
    fontSize?: number
    lineHeight?: number
    theme?: ITheme
    allowTransparency?: boolean
    convertEol?: boolean
    scrollback?: number
    [key: string]: any
  }

  export interface ITheme {
    background?: string
    foreground?: string
    cursor?: string
    selection?: string
    selectionBackground?: string
    black?: string
    red?: string
    green?: string
    yellow?: string
    blue?: string
    magenta?: string
    cyan?: string
    white?: string
    brightBlack?: string
    brightRed?: string
    brightGreen?: string
    brightYellow?: string
    brightBlue?: string
    brightMagenta?: string
    brightCyan?: string
    brightWhite?: string
  }

  export interface IDisposable {
    dispose(): void
  }

  export interface IMarker extends IDisposable {
    readonly id: number
    readonly isDisposed: boolean
    readonly line: number
  }

  export class Terminal {
    constructor(options?: ITerminalOptions)
    element: HTMLElement | undefined
    textarea: HTMLTextAreaElement | undefined
    cols: number
    rows: number
    buffer: { active: { cursorY: number; cursorX: number; length: number } }

    open(parent: HTMLElement): void
    write(data: string | Uint8Array, callback?: () => void): void
    writeln(data: string | Uint8Array, callback?: () => void): void
    clear(): void
    reset(): void
    resize(cols: number, rows: number): void
    scrollLines(amount: number): void
    scrollPages(pageCount: number): void
    scrollToTop(): void
    scrollToBottom(): void
    scrollToLine(line: number): void
    dispose(): void
    focus(): void
    blur(): void
    hasSelection(): boolean
    getSelection(): string
    clearSelection(): void
    selectAll(): void
    selectLines(start: number, end: number): void
    onData: IEvent<string>
    onKey: IEvent<{ key: string; domEvent: KeyboardEvent }>
    onResize: IEvent<{ cols: number; rows: number }>
    onScroll: IEvent<number>
    onSelectionChange: IEvent<void>
    onTitleChange: IEvent<string>
    onBell: IEvent<void>
    [key: string]: any
  }

  export interface IEvent<T> {
    (listener: (e: T) => any): IDisposable
    event?: (listener: (e: T) => any) => IDisposable
  }

  export interface ILinkProvider {
    provideLinks(
      bufferLineNumber: number,
      callback: (links: ILink[] | undefined) => void
    ): void
  }

  export interface ILink {
    range: IBufferRange
    text: string
    activate(event: MouseEvent, text: string): void
    hover?(event: MouseEvent, text: string): void
    leave?(event: MouseEvent, text: string): void
    [key: string]: any
  }

  export interface IBufferRange {
    start: IBufferCellPosition
    end: IBufferCellPosition
  }

  export interface IBufferCellPosition {
    x: number
    y: number
  }
}
