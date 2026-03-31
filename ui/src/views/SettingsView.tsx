import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { fetchProviderStatus, saveProviderConfig } from '../controllers/provider'


export default function SettingsView() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [apiBase, setApiBase] = useState('')
  const [savedKeyMask, setSavedKeyMask] = useState('')
  const [hasSavedKey, setHasSavedKey] = useState(false)

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const payload = await fetchProviderStatus()
        if (cancelled) {
          return
        }
        setApiBase(payload.custom_provider.api_base || '')
        setSavedKeyMask(payload.custom_provider.masked_api_key || '')
        setHasSavedKey(Boolean(payload.custom_provider.has_api_key))
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : 'Failed to load settings.')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [])

  async function handleSave(event: React.FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError('')
    setNotice('')

    try {
      const payload = await saveProviderConfig({
        api_key: apiKey,
        api_base: apiBase,
      })
      setApiBase(payload.custom_provider.api_base || '')
      setSavedKeyMask(payload.custom_provider.masked_api_key || '')
      setHasSavedKey(Boolean(payload.custom_provider.has_api_key))
      setNotice('Provider settings saved. New chat requests will use this global RoboClaw provider.')
      setApiKey('')
      window.setTimeout(() => navigate('/chat'), 600)
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Failed to save settings.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      <header className="bg-gray-800 border-b border-gray-700 p-4">
        <h2 className="text-xl font-semibold">设置</h2>
        <p className="mt-2 text-sm text-gray-400">
          这里只保留整个 RoboClaw 实例级别的全局 provider 配置。填写 base URL 和 API key 后，
          新的对话请求会直接使用这份配置。
        </p>
      </header>

      <div className="flex-1 p-6 max-w-3xl">
        {loading && <p className="text-gray-400">Loading provider settings...</p>}
        {!loading && (
          <form onSubmit={handleSave} className="space-y-6">
            {error && (
              <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-200">
                {error}
              </div>
            )}
            {notice && (
              <div className="rounded-lg border border-green-500/40 bg-green-500/10 p-4 text-green-200">
                {notice}
              </div>
            )}

            <section className="rounded-xl border border-gray-700 bg-gray-800/80 p-5 space-y-4">
              <h3 className="text-lg font-semibold">Global Provider</h3>

              <label className="block space-y-2">
                <span className="text-sm text-gray-300">Base URL</span>
                <input
                  value={apiBase}
                  onChange={(event) => setApiBase(event.target.value)}
                  className="w-full rounded-lg border border-gray-600 bg-gray-900 px-4 py-2 text-white"
                  placeholder="https://your-openai-compatible-endpoint/v1"
                />
              </label>

              <label className="block space-y-2">
                <span className="text-sm text-gray-300">API key</span>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  className="w-full rounded-lg border border-gray-600 bg-gray-900 px-4 py-2 text-white"
                  placeholder="留空表示保持当前 key 不变"
                />
              </label>

              <div className="rounded-lg border border-gray-700 bg-gray-900/60 p-3 text-sm text-gray-300">
                <div>当前保存状态: {hasSavedKey ? '已保存' : '未保存'}</div>
                {savedKeyMask && <div>已保存的 key: {savedKeyMask}</div>}
              </div>
            </section>

            <div className="flex items-center gap-4">
              <button
                type="submit"
                disabled={saving}
                className="rounded-lg bg-blue-600 px-5 py-2.5 text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-600"
              >
                {saving ? '保存中...' : '保存设置'}
              </button>
              <div className="text-sm text-gray-400">
                保存后会自动跳回聊天页。
              </div>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
