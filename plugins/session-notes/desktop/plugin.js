import { Button, Textarea, host, useValue } from '@hermes/plugin-sdk'
import { useCallback, useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'session-notes'

function makePane(ctx) {
  return function SummaryPane() {
    const sid = useValue(host.state.focusedStoredSessionId)
    const [text, setText] = useState('')
    const [saved, setSaved] = useState(false)
    const [busy, setBusy] = useState('')
    const [msg, setMsg] = useState('')
    const [showFmt, setShowFmt] = useState(false)
    const [fmt, setFmt] = useState('')

    const [fmtSrc, setFmtSrc] = useState('')

    useEffect(() => {
      ctx.rest(`/format?session_id=${encodeURIComponent(sid || '')}`)
        .then(r => { setFmt(r.format); setFmtSrc(r.source) }).catch(() => {})
    }, [sid])

    const saveFmt = async scope => {
      try {
        const r = await ctx.rest('/format', { method: 'POST', body: { session_id: sid, text: fmt, scope } })
        if (!r.ok) { setMsg(r.error); return }
        setFmt(r.format); setFmtSrc(r.source)
        setMsg({ session: 'Format saved for this session', default: 'Saved as default format (all sessions)',
                 reset: 'Session format cleared; using the ' + r.source + ' format' }[scope])
      } catch (e) { setMsg(String(e)) }
    }

    const load = useCallback(async () => {
      if (!sid) { setText(''); return }
      try {
        const r = await ctx.rest(`/draft?session_id=${encodeURIComponent(sid)}`)
        setText(r.draft || '')
        setSaved(!!r.saved)
        setMsg('')
      } catch (e) { setMsg(String(e)) }
    }, [sid])

    useEffect(() => { load() }, [load])

    const generate = async () => {
      setBusy('Summarizing… (can take up to a minute)'); setMsg('')
      try {
        const r = await ctx.rest('/generate', { method: 'POST', body: { session_id: sid, format: fmt }, timeoutMs: 300000 })
        if (r.ok) setText(r.draft); else setMsg(r.error || 'Failed')
      } catch (e) { setMsg(String(e)) }
      setBusy('')
    }

    const generateNew = async () => {
      setBusy('Summarizing new part…'); setMsg('')
      try {
        const r = await ctx.rest('/generate_new', { method: 'POST', body: { session_id: sid, text, format: fmt }, timeoutMs: 300000 })
        if (r.ok) setText(t => t.replace(/\n+$/, '') + (t.trim() ? '\n\n' : '') + r.chunk + '\n'); else setMsg(r.error || 'Failed')
      } catch (e) { setMsg(String(e)) }
      setBusy('')
    }

    const suggestTopics = async () => {
      setBusy('Suggesting topics…'); setMsg('')
      try {
        const r = await ctx.rest('/suggest_topics', { method: 'POST', body: { session_id: sid, text }, timeoutMs: 300000 })
        if (r.ok) { setText(r.draft); setMsg('Topics: ' + r.topics.join(', ')) } else setMsg(r.error || 'Failed')
      } catch (e) { setMsg(String(e)) }
      setBusy('')
    }

    const save = async () => {
      setBusy('Saving…'); setMsg('')
      try {
        const r = await ctx.rest('/save', { method: 'POST', body: { session_id: sid, text } })
        setMsg(r.message)
        if (r.ok) setSaved(true)
      } catch (e) { setMsg(String(e)) }
      setBusy('')
    }

    return jsxs('div', {
      className: 'flex h-full flex-col gap-2 p-3 text-sm',
      children: [
        jsx('div', { className: 'text-(--ui-text-tertiary) text-xs', children: sid ? `session: ${sid.slice(0, 18)}…` : 'No session selected' }),
        showFmt && jsxs('div', {
          className: 'flex flex-col gap-2',
          children: [
            jsx('div', { className: 'text-(--ui-text-tertiary) text-xs', children: 'Describe how summaries should be written (structure, length, language). Unsaved edits apply to the next summary only. Current source: ' + (fmtSrc || '…') + '.' }),
            jsx(Textarea, { className: 'h-28 text-xs', value: fmt, onChange: e => setFmt(e.target.value) }),
            jsxs('div', { className: 'flex flex-wrap gap-2', children: [
              jsx(Button, { onClick: () => saveFmt('session'), disabled: !sid, children: 'Save for this session' }),
              jsx(Button, { onClick: () => saveFmt('default'), children: 'Save as default' }),
              jsx(Button, { onClick: () => saveFmt('reset'), disabled: !sid, children: 'Reset' })
            ] })
          ]
        }),
        jsx(Textarea, {
          className: 'min-h-0 flex-1 font-mono text-xs',
          value: text,
          placeholder: saved ? 'Already saved to Notion' : 'No draft yet. Click Summarize whole session.',
          onChange: e => setText(e.target.value)
        }),
        jsxs('div', {
          className: 'flex flex-wrap gap-2',
          children: [
            jsx(Button, { onClick: generate, disabled: !sid || !!busy, children: 'Summarize whole session' }),
            jsx(Button, { onClick: generateNew, disabled: !sid || !!busy, children: 'Summarize new' }),
            jsx(Button, { onClick: suggestTopics, disabled: !sid || !text || !!busy, children: 'Suggest topics' }),
            jsx(Button, { onClick: () => setShowFmt(v => !v), children: showFmt ? 'Hide format' : 'Format…' }),
            jsx(Button, { onClick: save, disabled: !sid || !text || !!busy, children: 'Save to Notion' })
          ]
        }),
        (busy || msg) && jsx('div', { className: 'text-(--ui-text-secondary) text-xs', children: busy || msg })
      ]
    })
  }
}

export default {
  id: ID,
  name: 'Session Notes',
  register(ctx) {
    ctx.register({
      id: 'pane',
      area: 'panes',
      title: 'Summary',
      data: { placement: 'right', width: '320px' },
      render: () => jsx(makePane(ctx), {})
    })
  }
}
