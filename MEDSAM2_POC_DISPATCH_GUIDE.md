# MedSAM2 POC 入口调度说明（重点: Prompt 形式与差异）

本文档只针对 `seg-entry` 中 `model=medsam2` 的 POC 调度使用。

## 1. 适用范围

- 当前目标: `liver`
- 当前 POC 产物: `liver_tumor.nii.gz`（提示驱动肝肿瘤分割）
- 输入支持: `nifti_file`、`dicom_dir`
- 设备要求: `gpu`（当前不支持 CPU 推理）

## 2. 和 TotalSegmentator 的关键差异

1. 调度范式不同
- `totalsegmentator`: 无 prompt，给影像即跑。
- `medsam2`: 必须带 prompt，属于“交互提示驱动”的 3D 分割。

2. 请求必填项不同
- `totalsegmentator`: `prompts` 可为空。
- `medsam2`: `prompts` 必填，且每个 prompt 必须是支持的类型。

3. Prompt 语义不同
- `totalsegmentator`: 不消费 `frame_index/bbox/points`。
- `medsam2`: 强依赖 `frame_index + (bbox 或 points)`。

4. 当前输出定位不同
- `totalsegmentator`: 偏“肝脏整体及子任务”。
- `medsam2`: 当前 POC 偏“肝肿瘤目标区域（提示驱动）”。

5. 引擎参数不同
- `medsam2` 额外支持: `medsam2_runner`、`medsam2_ckpt`、`medsam2_config`、`medsam2_image_size`。

## 3. 调度入口（seg-entry）

统一入口仍是 `seg-entry`，`model` 改成 `medsam2`。

CLI 示例（推荐先跑这个）：

```bash
python3 -m seg_entry.cli run \
  --model medsam2 \
  --input-path /path/to/case.nii.gz \
  --input-type nifti_file \
  --prompt-json /mnt/midstorage/user/wya/seg/seg-entry/examples/request_medsam2_liver_prompt.json \
  --device gpu \
  --output-dir /tmp/seg-entry-demo/medsam2-poc-001 \
  --pretty
```

HTTP 入口同样走 `POST /segmentations`，请求体结构与 CLI 的 JSON 一致。

## 4. Prompt 形式（你最关心的部分）

`medsam2` 当前支持 3 类 prompt：

1. `bbox_2d`
2. `points_2d`
3. `diameter_line_2d`

通用字段：

- `kind`: prompt 类型
- `frame_index`: 提示所在切片索引（0-based）
- `metadata`（可选）: 透传元数据

坐标约定：

- 2D 像素坐标
- `x` 为列方向（从左到右）
- `y` 为行方向（从上到下）
- 使用原始切片坐标系（不是归一化 0~1）

### 4.1 `bbox_2d`

字段要求：

- `bbox`: `[x0, y0, x1, y1]`

示例：

```json
{
  "kind": "bbox_2d",
  "frame_index": 87,
  "bbox": [160, 120, 350, 320]
}
```

### 4.2 `points_2d`

字段要求：

- `points`: 点数组
- 每个点: `{ "x": number, "y": number, "label": 0|1 }`

说明：

- `label=1`: 前景正点
- `label=0`: 背景负点（用于抑制误分）

示例：

```json
{
  "kind": "points_2d",
  "frame_index": 87,
  "points": [
    { "x": 232, "y": 188, "label": 1 },
    { "x": 190, "y": 165, "label": 0 }
  ]
}
```

### 4.3 `diameter_line_2d`

用途：把“最大径线标注”直接映射为两个端点输入。

字段要求：

- `points`: 一组线端点（通常 2 个点）
- 格式同 `points_2d`

示例：

```json
{
  "kind": "diameter_line_2d",
  "frame_index": 92,
  "points": [
    { "x": 210, "y": 176, "label": 1 },
    { "x": 286, "y": 174, "label": 1 }
  ],
  "metadata": {
    "tool": "ohif_length"
  }
}
```

### 4.4 实现行为细节（POC 必看）

1. `frame_index` 缺失时
- 代码会默认取体数据中间层。

2. `frame_index` 越界时
- 会被裁剪到合法范围（`0 ~ frame_count-1`）。

3. 多个 prompt 的处理
- 可同时提交多个 prompt（可跨层）。
- 当前实现把 prompt 合并为同一个目标对象（单对象 POC 逻辑）。

4. 传播起点
- 实际传播从最早的 prompt 层开始，再做正向+反向传播覆盖整段体数据。

## 5. POC 请求示例（建议直接复用）

完整请求（可作为 `request-json`）：

```json
{
  "request_id": "poc-medsam2-liver-tumor-001",
  "input_path": "/data/cases/liver_case_001.nii.gz",
  "input_type": "nifti_file",
  "target": "liver",
  "model": "medsam2",
  "modality": "ct",
  "output_dir": "/tmp/seg-entry-demo/poc-medsam2-liver-tumor-001",
  "prompts": [
    {
      "kind": "diameter_line_2d",
      "frame_index": 92,
      "points": [
        { "x": 210, "y": 176, "label": 1 },
        { "x": 286, "y": 174, "label": 1 }
      ]
    }
  ],
  "engine": {
    "device": "gpu",
    "gpu_policy": "auto_best",
    "gpu_candidates": "0,1,2,3,4,5,6,7",
    "gpu_min_free_memory_mb": 4096,
    "medsam2_runner": "/mnt/midstorage/user/wya/seg/Medical-SAM2/scripts/run_liver_prompt_workflow.py",
    "medsam2_ckpt": "/mnt/midstorage/user/wya/seg/Medical-SAM2/checkpoints/sam2_hiera_small.pt",
    "medsam2_config": "sam2_hiera_s",
    "medsam2_image_size": 1024
  }
}
```

## 6. 调度执行链路（内部）

`seg-entry` 内部执行顺序：

1. `SegmentationService.execute`
2. `MedSam2Adapter.validate_request`
3. `MedSam2Adapter.run`（写 `plans/medsam2_case.json`）
4. 子进程调用 `Medical-SAM2/scripts/run_liver_prompt_workflow.py _worker`
5. `local_workflow.run_case -> run_task -> run_prompt_inference`
6. 输出 `engine/medsam2/<case_id>/tasks/...` 并导出到 `exports/`

## 7. 结果和查看方式

一次成功请求后，重点看：

- `<output_dir>/response.json`
- `<output_dir>/logs/medsam2.log`
- `<output_dir>/engine/medsam2/<case_id>/exports/liver_tumor.nii.gz`
- `<output_dir>/engine/medsam2/<case_id>/exports/liver_tumor_diameter.json`
- `<output_dir>/engine/medsam2/<case_id>/exports/prompt_plan.json`
- `<output_dir>/engine/medsam2/<case_id>/exports/prompt_render_primary.png`
- `<output_dir>/engine/medsam2/<case_id>/exports/prompt_render_index.json`

其中：

- `liver_tumor.nii.gz`: 主分割结果（标准分割 artifact）
- `liver_tumor_diameter.json`: 基于预测掩码计算的最大径结果
- `prompt_plan.json`: 归一化后的 prompt 落盘，便于回放和审计
- `prompt_render_primary.png`: 你标注切片上的“切片+标注”直观预览图
- `prompt_render_index.json`: 所有渲染 PNG 的索引及主预览指针

## 8. POC 阶段建议的 prompt 策略

1. 首选 `diameter_line_2d`
- 最贴合甲方“最大径线标注”工作流。

2. 次选 `bbox_2d`
- UI 成本低，适合先快速验证可用性。

3. 精修用 `points_2d`
- 在误分区域加 `label=0` 负点做约束。

## 9. 常见失败与排查

1. `prompt_required`
- 原因: `prompts` 为空。
- 处理: 至少传一个有效 prompt。

2. `unsupported_prompt_kind`
- 原因: `kind` 非 `bbox_2d/points_2d/diameter_line_2d`。
- 处理: 修正类型名。

3. `invalid_device`
- 原因: 传了 `cpu`。
- 处理: 使用 `device=gpu`。

4. `medsam2_ckpt_not_found`
- 原因: 权重路径不正确。
- 处理: 指向有效 checkpoint 文件。

5. `medsam2_run_failed`
- 原因: 模型执行期异常。
- 处理: 看 `<output_dir>/logs/medsam2.log`。

## 10. 对接 OHIF 的最小映射建议

1. 框选工具 -> `bbox_2d`
2. 测量线工具（Length）两端点 -> `diameter_line_2d`
3. 额外修正点 -> `points_2d`（带 `label=0/1`）

这样就可以把“最大径层面框选/画线 -> 自动分割返回”串成稳定 POC 闭环。
