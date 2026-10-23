// 사용자 결정 2026-10-23 : 화면은 옵시디언 + 대시보드 느낌 - 왼쪽 탐색기, 가운데 탭, 오른쪽 연결 패널, 아래 상태 막대
// 사용자 결정 2026-10-23 : 들어오는 링크 ( 백링크 같은 것 ) 는 보여 주지 않는다 - 고정 결정 "백링크 미기록" 과 헷갈리지 않게
// 사용자 결정 2026-10-21 · 23 : 보는 사람별 거르기는 서버가 하고 화면은 받은 것만 그린다. 보는 사람 선택은 인증이 아니다
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchMeetings, type Mode, type Viewer } from './api'
import { CompareMode } from './CompareMode'
import { CompareViewer } from './CompareViewer'
import { Dashboard } from './Dashboard'
import { GraphTab } from './GraphTab'
import { LiveTab } from './LiveTab'
import { MeetingPage } from './MeetingPage'
import { MeetingsTab } from './MeetingsTab'
import { NoteReader } from './NoteReader'
import { loadPanelState, savePanelState, type Panel, type PanelState } from './panelWidth'
import { Resizer } from './Resizer'
import { MODE_LABEL, Sidebar } from './Sidebar'
import {
  activate, closeTab, COMPARE_MODE_TAB, COMPARE_VIEWER_TAB, DASHBOARD_TAB, GRAPH_TAB, INITIAL_TABS, noteIdOfTab, openTab,
  LIVE_TAB, meetingIdOfTab, MEETINGS_TAB, openMeetingTab, syncTabs, type TabState,
} from './tabs'
import { useView } from './useView'

export function Workspace({
  viewer,
  viewers,
  showNames,
  baseRun,
  onChangeViewer,
}: {
  viewer: Viewer
  viewers: Viewer[]
  showNames: boolean
  baseRun: string | null
  onChangeViewer: () => void
}) {
  const [mode, setMode] = useState<Mode>('all_layers')
  // 보는 사람을 고르면 두 모드의 보기를 모두 불러 둔다 - 대시보드가 두 모드를 나란히 센다
  // 라이브 겹침 : overlay.mode 와 같은 모드의 보기에만 jobId 를 넘긴다 - 다른 모드는 기본 볼트다
  const [overlay, setOverlay] = useState<{ mode: Mode; jobId: string } | null>(null)
  const jobFor = (m: Mode) => (overlay && overlay.mode === m ? overlay.jobId : null)
  const allLayers = useView('all_layers', viewer.viewer_id, jobFor('all_layers'))
  const splitByLayer = useView('split_by_layer', viewer.viewer_id, jobFor('split_by_layer'))
  const views = { all_layers: allLayers, split_by_layer: splitByLayer }
  const current = views[mode]
  const [tabs, setTabs] = useState<TabState>(INITIAL_TABS)
  const [showSameLayer, setShowSameLayer] = useState(true)
  // 탐색기 · 연결 패널의 폭과 접힘 - 저장할 때 최신 값을 쓰려고 ref 에도 둔다 ( 오래된 값 저장 금지 )
  const [panels, setPanels] = useState<PanelState>(loadPanelState)
  const panelsRef = useRef(panels)
  panelsRef.current = panels
  const updatePanels = useCallback((next: PanelState, save: boolean) => {
    // 키보드 · 접기는 바꾼 직후 바로 저장하므로 ref 도 함께 갱신해 같은 틱의 저장이 새 값을 쓰게 한다
    panelsRef.current = next
    setPanels(next)
    if (save) savePanelState(next)
  }, [])
  const changeWidth = useCallback(
    (panel: Panel, px: number) => {
      const current = panelsRef.current
      updatePanels({ ...current, widths: { ...current.widths, [panel]: px } }, false)
    },
    [updatePanels],
  )
  const commitPanels = useCallback(() => savePanelState(panelsRef.current), [])
  // 접어도 widths 는 그대로 두어 펼 때 마지막 폭으로 돌아온다
  const setCollapsed = useCallback(
    (panel: Panel, collapsed: boolean) => {
      const current = panelsRef.current
      updatePanels({ ...current, collapsed: { ...current.collapsed, [panel]: collapsed } }, true)
    },
    [updatePanels],
  )
  const columnWidth = (panel: Panel) => (panels.collapsed[panel] ? 0 : panels.widths[panel])
  // 회의 탭 : 회의가 바뀌면 version 을 올려 목록 · 탭 제목을 다시 불러온다 - 보는 사람을 바꾸면 Workspace 가 다시 그려져 열린 회의 탭은 사라진다
  const [meetingVersion, setMeetingVersion] = useState(0)
  const [meetingTitles, setMeetingTitles] = useState<Map<string, string>>(new Map())
  useEffect(() => {
    let alive = true
    // 503 이나 실패면 탭 제목을 id 로 둔다 - 안내는 회의 탭이 보인다
    fetchMeetings(viewer.viewer_id)
      .then((list) => alive && setMeetingTitles(new Map(list.map((m) => [m.meeting_id, m.title]))))
      .catch(() => alive && setMeetingTitles(new Map()))
    return () => {
      alive = false
    }
  }, [viewer.viewer_id, meetingVersion])
  const openMeeting = (meetingId: string) => setTabs((state) => openMeetingTab(state, meetingId))
  const [graphSelected, setGraphSelected] = useState<string | null>(null)

  const notes = current.data?.notes ?? null
  const titles = useMemo(() => new Map((notes ?? []).map((n) => [n.note_id, n.title])), [notes])
  // 모드를 바꿔 보기가 달라지면 새 보기에 없는 노트의 탭과 그래프 선택을 닫는다
  useEffect(() => {
    if (!notes) return
    const ids = new Set(notes.map((n) => n.note_id))
    setTabs((state) => syncTabs(state, ids))
    setGraphSelected((id) => (id !== null && ids.has(id) ? id : null))
  }, [notes])

  const openNote = (noteId: string) => {
    setTabs((state) => openTab(state, noteId))
    setGraphSelected(noteId)
  }
  // 모드 비교 표에서 노트를 누르면 그 노트가 나온 모드로 바꾸고 노트 탭을 연다
  const openNoteInMode = (nextMode: Mode, noteId: string) => {
    setMode(nextMode)
    openNote(noteId)
  }
  const activeNoteId = noteIdOfTab(tabs.active)
  const activeNote = notes?.find((n) => n.note_id === activeNoteId) ?? null

  const center = () => {
    if (current.error) return <div className="notice error">오류 : {current.error}</div>
    if (tabs.active === DASHBOARD_TAB) return <Dashboard mode={mode} views={views} viewer={viewer} showNames={showNames} onOpenNote={openNote} />
    if (tabs.active === MEETINGS_TAB) {
      return <MeetingsTab viewer={viewer} version={meetingVersion} onOpenMeeting={openMeeting} />
    }
    const activeMeetingId = meetingIdOfTab(tabs.active)
    if (activeMeetingId !== null) {
      return (
        <MeetingPage
          key={activeMeetingId}
          viewer={viewer}
          meetingId={activeMeetingId}
          view={current.data}
          onOpenNote={openNote}
          onChanged={() => setMeetingVersion((n) => n + 1)}
          onOtherMode={() => setMode((m) => (m === 'all_layers' ? 'split_by_layer' : 'all_layers'))}
        />
      )
    }
    if (tabs.active === COMPARE_VIEWER_TAB) {
      return <CompareViewer viewer={viewer} viewers={viewers} mode={mode} viewA={current.data} jobId={jobFor(mode)} onOpenNote={openNote} />
    }
    if (tabs.active === LIVE_TAB) {
      return (
        <LiveTab
          defaultMode={mode}
          onOverlay={(overlayMode, jobId) => {
            // 겹쳐 보기를 누르면 그 모드로 바꾸고 그래프에서 바로 보이게 한다
            setOverlay({ mode: overlayMode, jobId })
            setMode(overlayMode)
            setTabs((s) => activate(s, GRAPH_TAB))
          }}
        />
      )
    }
    if (tabs.active === COMPARE_MODE_TAB) {
      return <CompareMode views={views} showNames={showNames} onOpenNoteInMode={openNoteInMode} />
    }
    if (!current.data) return <div className="notice">불러오는 중</div>
    if (tabs.active === GRAPH_TAB) {
      return (
        <GraphTab
          data={current.data}
          showSameLayer={showSameLayer}
          onToggleSameLayer={setShowSameLayer}
          selectedId={graphSelected}
          onOpenNote={openNote}
        />
      )
    }
    return activeNote ? (
      <NoteReader note={activeNote} titles={titles} showNames={showNames} onOpenNote={openNote} />
    ) : (
      <div className="notice">이 보기에 없는 노트</div>
    )
  }

  const tabLabel = (key: string) => {
    if (key === DASHBOARD_TAB) return '대시보드'
    if (key === GRAPH_TAB) return '그래프'
    if (key === MEETINGS_TAB) return '회의'
    if (key === COMPARE_VIEWER_TAB) return '보는 사람 비교'
    if (key === COMPARE_MODE_TAB) return '모드 비교'
    if (key === LIVE_TAB) return '라이브 투입'
    const meetingId = meetingIdOfTab(key)
    if (meetingId !== null) return meetingTitles.get(meetingId) ?? meetingId
    const id = noteIdOfTab(key)
    return (id && titles.get(id)) || id || key
  }

  return (
    <div
      className="shell"
      // 접힌 패널 칸은 0px 이고 손잡이 6px 칸은 남긴다 - 접힌 패널은 없애지 않고 칸 폭 0 + overflow hidden 으로 감춰 펼침 상태 · 스크롤 위치를 유지한다
      data-sidebar-collapsed={panels.collapsed.sidebar}
      data-connections-collapsed={panels.collapsed.connections}
      style={{ gridTemplateColumns: `76px ${columnWidth('sidebar')}px 6px minmax(0, 1fr) 6px ${columnWidth('connections')}px` }}
    >
      <aside className="ribbon">
        <div className="ribbon-top">
          <button aria-pressed={!panels.collapsed.sidebar} onClick={() => setCollapsed('sidebar', !panels.collapsed.sidebar)}>
            탐색기
          </button>
          <button className={tabs.active === DASHBOARD_TAB ? 'on' : ''} onClick={() => setTabs((s) => activate(s, DASHBOARD_TAB))}>
            대시보드
          </button>
          <button className={tabs.active === GRAPH_TAB ? 'on' : ''} onClick={() => setTabs((s) => activate(s, GRAPH_TAB))}>
            그래프
          </button>
          <button className={tabs.active === MEETINGS_TAB ? 'on' : ''} onClick={() => setTabs((s) => activate(s, MEETINGS_TAB))}>
            회의
          </button>
          <button
            className={tabs.active === COMPARE_VIEWER_TAB ? 'on' : ''}
            onClick={() => setTabs((s) => activate(s, COMPARE_VIEWER_TAB))}
          >
            보는 사람 비교
          </button>
          <button
            className={tabs.active === COMPARE_MODE_TAB ? 'on' : ''}
            onClick={() => setTabs((s) => activate(s, COMPARE_MODE_TAB))}
          >
            모드 비교
          </button>
          <button className={tabs.active === LIVE_TAB ? 'on' : ''} onClick={() => setTabs((s) => activate(s, LIVE_TAB))}>
            라이브 투입
          </button>
        </div>
        <button onClick={onChangeViewer}>보는 사람 바꾸기</button>
      </aside>
      <Sidebar viewer={viewer} mode={mode} onMode={setMode} notes={notes} activeNoteId={activeNoteId} onOpenNote={openNote} />
      <Resizer
        panel="sidebar"
        width={panels.widths.sidebar}
        direction={1}
        onChange={(px) => changeWidth('sidebar', px)}
        onCommit={commitPanels}
        collapsed={panels.collapsed.sidebar}
        onCollapse={() => setCollapsed('sidebar', true)}
        onExpand={() => setCollapsed('sidebar', false)}
      />
      <main className="center">
        <div className="tabbar">
          {tabs.tabs.map((key) => (
            <div key={key} className={key === tabs.active ? 'tab on' : 'tab'}>
              <button className="tab-name" onClick={() => setTabs((s) => activate(s, key))}>
                {tabLabel(key)}
              </button>
              {(noteIdOfTab(key) !== null || meetingIdOfTab(key) !== null) && (
                <button className="tab-close" aria-label="탭 닫기" onClick={() => setTabs((s) => closeTab(s, key))}>
                  ×
                </button>
              )}
            </div>
          ))}
        </div>
        <div className="tab-body">{center()}</div>
      </main>
      <Resizer
        panel="connections"
        width={panels.widths.connections}
        direction={-1}
        onChange={(px) => changeWidth('connections', px)}
        onCommit={commitPanels}
        collapsed={panels.collapsed.connections}
        onCollapse={() => setCollapsed('connections', true)}
        onExpand={() => setCollapsed('connections', false)}
      />
      <aside className="connections">
        <h3>연결</h3>
        {activeNote ? (
          <>
            <p className="muted">{activeNote.title}</p>
            <h4>상향 링크</h4>
            <LinkList ids={activeNote.upward_links} titles={titles} onOpenNote={openNote} />
            <h4>열린 하향 조건부 링크</h4>
            <LinkList ids={activeNote.opened_downward_links} titles={titles} onOpenNote={openNote} />
          </>
        ) : current.data ? (
          <>
            <p className="muted">이 보기의 링크 수</p>
            <dl className="props">
              <dt>열린 하향 조건부 링크</dt>
              <dd>{current.data.counts.conditional_links_opened}</dd>
              <dt>가려진 하향 조건부 링크</dt>
              <dd>{current.data.counts.conditional_links_hidden}</dd>
              <dt>가려진 상향 링크</dt>
              <dd>{current.data.counts.upward_links_hidden}</dd>
            </dl>
          </>
        ) : (
          <p className="muted">불러오는 중</p>
        )}
      </aside>
      <footer className="status">
        <span>시연 경로 · 합성 코퍼스 ( 스냅샷 900 )</span>
        <span>기본 실행 : {baseRun ?? '확인 못 함'}</span>
        <span>{showNames ? '이름 · 본문 표시' : '이름 · 본문 가려짐'}</span>
        <span>지금 모드 : {MODE_LABEL[mode]}</span>
        {overlay && (
          <span>
            {`라이브 겹침 : ${overlay.jobId.slice(0, 8)} ( ${MODE_LABEL[overlay.mode]} ) `}
            <button className="overlay-off" onClick={() => setOverlay(null)}>
              겹침 끄기
            </button>
          </span>
        )}
        <button
          className="status-toggle"
          aria-pressed={!panels.collapsed.connections}
          onClick={() => setCollapsed('connections', !panels.collapsed.connections)}
        >
          연결 패널
        </button>
      </footer>
    </div>
  )
}

function LinkList({ ids, titles, onOpenNote }: { ids: string[]; titles: Map<string, string>; onOpenNote: (id: string) => void }) {
  if (ids.length === 0) return <p className="muted">없음</p>
  return (
    <ul className="links">
      {ids.map((id) => (
        <li key={id}>
          <button className="link" onClick={() => onOpenNote(id)}>
            {titles.get(id) ?? id}
          </button>
        </li>
      ))}
    </ul>
  )
}
