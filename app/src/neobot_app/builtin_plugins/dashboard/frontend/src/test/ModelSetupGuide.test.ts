// 「接入模型」教程的判据逻辑。
//
// 自动弹出的条件必须是「模型库为空」——它同时是后端进入待机的原因
// （bootstrap 的 _models_not_configured），前后端用同一个概念，避免两套标准。
import { describe, expect, it } from 'vitest';
import { isModelLibraryEmpty, isPrimaryAssigned } from '../pages/config/ModelSetupGuide';
import type { ModelsPayload } from '../api/types';

describe('接入模型教程：判据', () => {
  it('取不到状态时视为「库为空」，教程应当弹出（宁可多弹，不可卡住新用户）', () => {
    expect(isModelLibraryEmpty(null)).toBe(true);
  });

  it('出厂状态（库为空）→ 需要弹出教程', () => {
    const payload = { library: [] } as ModelsPayload;
    expect(isModelLibraryEmpty(payload)).toBe(true);
  });

  it('已有模型 → 不再自动弹出', () => {
    const payload = { library: [{ key: 'my-model' }] } as ModelsPayload;
    expect(isModelLibraryEmpty(payload)).toBe(false);
  });

  it('库字段缺失也按空处理（接口形状变化时不至于静默不弹）', () => {
    const payload = {} as ModelsPayload;
    expect(isModelLibraryEmpty(payload)).toBe(true);
  });
});

describe('接入模型教程：主对话模型是否已分配', () => {
  it('未分配 → 第三步未完成', () => {
    expect(isPrimaryAssigned({ assignments: {} } as ModelsPayload)).toBe(false);
    expect(isPrimaryAssigned({ assignments: { primary_chat_model: '' } } as ModelsPayload)).toBe(false);
    expect(isPrimaryAssigned({ assignments: { primary_chat_model: '   ' } } as ModelsPayload)).toBe(false);
    expect(isPrimaryAssigned(null)).toBe(false);
  });

  it('已分配 → 第三步完成', () => {
    expect(
      isPrimaryAssigned({ assignments: { primary_chat_model: 'my-model' } } as ModelsPayload),
    ).toBe(true);
  });
});
