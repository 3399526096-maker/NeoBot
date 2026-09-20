// pages/config/ModelSetupGuide.tsx —— 「接入模型」新手教程
//
// 出厂模型库是空的（见 schemas/bot.py 的 _default_model_library：新用户自行导入模型），
// 而接入流程要跨三个页签（环境变量 → 模型库 → 模型分配），新用户很容易卡在第一步不知道怎么走。
// 这个组件把三步讲清楚：
//   * 模型库为空时**自动弹出**（首次配置）
//   * 之后随时可以从页签栏的「教程」按钮再打开
//   * 每一步的完成状态都来自真实数据，不是写死的
import { useMemo } from 'react';
import type { ModelsPayload } from '../../api/types';
import Icon from '../../components/Icon';
import Modal from '../../components/Modal';

interface GuideProps {
  open: boolean;
  onClose: () => void;
  onGoTab: (tab: string) => void;
  payload: ModelsPayload | null;
  onRefresh: () => void;
}

interface StepSpec {
  key: string;
  title: string;
  tab: string;
  tabLabel: string;
  detail: string;
  done: boolean;
}

/** 模型库是否还空着 —— 也就是「尚未接入模型」的判据（与后端待机原因一致）。 */
export function isModelLibraryEmpty(payload: ModelsPayload | null): boolean {
  return !payload || !(payload.library || []).length;
}

/** 主对话模型是否已分配。 */
export function isPrimaryAssigned(payload: ModelsPayload | null): boolean {
  const assignments = (payload?.assignments || {}) as Record<string, unknown>;
  return String(assignments.primary_chat_model || '').trim().length > 0;
}

export function ModelSetupGuide({ open, onClose, onGoTab, payload, onRefresh }: GuideProps) {
  const steps = useMemo<StepSpec[]>(() => {
    const providers = payload?.provider_options || [];
    const library = payload?.library || [];
    return [
      {
        key: 'env',
        title: '第一步：添加模型供应商',
        tab: 'env',
        tabLabel: '环境变量',
        detail:
          '在「环境变量」页点「添加供应商」，填平台地址（Base URL）和 API Key。' +
          (providers.length ? `目前可选平台：${providers.slice(0, 6).join('、')}。` : ''),
        done: false, // 供应商是否已配置由 .env 决定，这里不猜
      },
      {
        key: 'models',
        title: '第二步：把模型加进模型库',
        tab: 'models',
        tabLabel: '模型库',
        detail:
          '在「模型库」页点「新增模型」，选好供应商后点「拉取供应商模型」会自动列出该 Key 可用的模型，' +
          '勾一个填进去即可；保存前可以点「测试连通性」确认能连上。',
        done: library.length > 0,
      },
      {
        key: 'assign',
        title: '第三步：分配角色',
        tab: 'assign',
        tabLabel: '模型分配',
        detail:
          '在「模型分配」页把「主对话模型」指到刚加的模型上。视觉/语音/生图可以留空，' +
          '对应的功能会自动禁用，不影响聊天。',
        done: isPrimaryAssigned(payload),
      },
    ];
  }, [payload]);

  const doneCount = steps.filter((step) => step.done).length;

  return (
    <Modal open={open} size="wide" title="接入模型 · 三步走" onClose={onClose}>
      <div className="stack">
        <p className="muted small" style={{ marginTop: 0 }}>
          出厂不带任何模型 —— 模型库是空的，需要你接入自己的供应商与模型。
          完成后点面板上的「软重启运行」即可开始聊天。
        </p>

        <div className="muted small">
          进度：{doneCount} / {steps.length} 步完成
        </div>

        <ol className="stack" style={{ paddingLeft: 18, margin: 0 }}>
          {steps.map((step) => (
            <li key={step.key} style={{ marginBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Icon name={step.done ? 'check' : 'more'} />
                <strong>{step.title}</strong>
                {step.done && <span className="muted small">已完成</span>}
              </div>
              <div className="muted small" style={{ margin: '4px 0 6px' }}>
                {step.detail}
              </div>
              <button
                className="btn-sm"
                onClick={() => {
                  onGoTab(step.tab);
                  onClose();
                }}
              >
                去「{step.tabLabel}」
              </button>
            </li>
          ))}
        </ol>

        <p className="muted small" style={{ marginBottom: 0 }}>
          每一步做完可以回到这里点「刷新」看进度；这个教程之后也能从页签栏的「教程」按钮再次打开。
        </p>
      </div>

      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 }}>
        <button className="btn-sm" onClick={onRefresh}>
          刷新进度
        </button>
        <button className="btn" onClick={onClose}>
          知道了
        </button>
      </div>
    </Modal>
  );
}
