// 사용자 결정 2026-10-23 : 노션 토글 블록 - 제목 앞 ▸ / ▾, 누르면 접고 편다. 접힘 상태는 이 컴포넌트 안에만 있고 저장하지 않는다
import { useState, type ReactNode } from 'react'

export function Toggle({ title, children, defaultOpen = true }: { title: string; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="toggle-block">
      <button className="toggle-head" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <span className="caret">{open ? '▾' : '▸'}</span>
        {title}
      </button>
      {open && <div className="toggle-body">{children}</div>}
    </section>
  )
}
