// pages/ConfigManager.tsx —— 配置管理入口：只负责顶层 tab 路由，各面板独立成文件
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { api } from '../api/endpoints';
import type { ModelsPayload } from '../api/types';
import { BotConfigPanel } from './config/BotConfigPanel';
import { EnvPanel } from './config/EnvPanel';
import { ModelsPanel } from './config/ModelsPanel';
import { AssignPanel } from './config/AssignPanel';
import { ModelSetupGuide, isModelLibraryEmpty } from './config/ModelSetupGuide';

const TABS: Array<[string, string]> = [
  ['config', '本体配置'],
  ['env', '环境变量'],
  ['models', '模型库'],
  ['assign', '模型分配'],
];

export default function ConfigManager() {
  const [tab, setTab] = useState('config');
  const editorState = useRef({ dirty: false, busy: false });
  const [busy, setBusy] = useState(false);

  // 接入模型的新手教程：模型库为空（出厂状态）时自动弹出一次，
  // 之后随时可以从页签栏的「教程」按钮再打开。
  const [guideOpen, setGuideOpen] = useState(false);
  const [models, setModels] = useState<ModelsPayload | null>(null);
  const autoOpened = useRef(false);

  const refreshModels = useCallback(async () => {
    try {
      const result = await api.configModels();
      if (!result.ok || !result.data) return null;
      setModels(result.data);
      return result.data;
    } catch {
      // 取不到状态时不要打扰用户（不自动弹教程），功能本身不受影响
      return null;
    }
  }, []);

  useEffect(() => {
    void refreshModels().then((payload) => {
      if (payload && !autoOpened.current && isModelLibraryEmpty(payload)) {
        autoOpened.current = true;
        setGuideOpen(true);
      }
    });
  }, [refreshModels]);

  useLayoutEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<boolean | { dirty: boolean; busy: boolean }>).detail;
      editorState.current = typeof detail === 'boolean' ? { dirty: detail, busy: false } : detail;
      setBusy(editorState.current.busy);
    };
    window.addEventListener('dashboard-editor-state', handler);
    return () => {
      window.removeEventListener('dashboard-editor-state', handler);
      editorState.current = { dirty: false, busy: false };
      window.dispatchEvent(new CustomEvent('dashboard-editor-state', { detail: { dirty: false, busy: false } }));
    };
  }, []);
  const switchTab = (next: string) => {
    if (next === tab || editorState.current.busy) return;
    if (editorState.current.dirty && !confirm('切换配置页会丢弃未保存的修改，确认继续？')) return;
    editorState.current = { dirty: false, busy: false };
    window.dispatchEvent(new CustomEvent('dashboard-editor-state', { detail: editorState.current }));
    setTab(next);
    void refreshModels();
  };
  return (
    <div className="page config-page">
      <div className="config-tabs cfg-top-tabs">
        <div role="tablist" aria-label="配置管理">
          {TABS.map(([key, label]) => (
            <button
              key={key}
              role="tab"
              aria-selected={tab === key}
              className={tab === key ? 'active' : ''}
              disabled={busy}
              onClick={() => switchTab(key)}
            >
              {label}
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button className="btn-sm" onClick={() => setGuideOpen(true)}>
            教程
          </button>
          <span className="muted small">config.toml / .env / 模型库与分配</span>
        </div>
      </div>
      {tab === 'config' && <BotConfigPanel />}
      {tab === 'env' && <EnvPanel />}
      {tab === 'models' && <ModelsPanel />}
      {tab === 'assign' && <AssignPanel />}
      <ModelSetupGuide
        open={guideOpen}
        onClose={() => setGuideOpen(false)}
        onGoTab={switchTab}
        payload={models}
        onRefresh={() => void refreshModels()}
      />
    </div>
  );
}
