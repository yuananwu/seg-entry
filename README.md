# seg-entry

`seg-entry` 是这一套分割能力的标准化入口层。  
它不直接把某个模型写死，而是把下面几件事统一起来：

- 输入统一: 支持 `DICOM` 目录和 `nii/nii.gz`
- 请求统一: 用固定 JSON 描述 `input`、`target`、`model`、`modality`、`prompts`
- 调度统一: 通过模型适配器去调用不同分割引擎
- 输出统一: 固定返回 `response.json`、主分割结果路径、附加产物路径
- 对接统一: 既能本地 CLI 调用，也能通过 HTTP 给后续 Orthanc 使用

模型接入标准见：

- [MODEL_INTEGRATION_STANDARD.md](/mnt/midstorage/user/wya/seg/seg-entry/MODEL_INTEGRATION_STANDARD.md)
- [DEVELOPER_INTERFACE_GUIDE.md](/mnt/midstorage/user/wya/seg/seg-entry/DEVELOPER_INTERFACE_GUIDE.md)

Orthanc 对接规范见：

- [ORTHANC_INTEGRATION_SPEC.md](/mnt/midstorage/user/wya/seg/seg-entry/ORTHANC_INTEGRATION_SPEC.md)

## 这一版的范围

- 目标: `liver`、`mr_abdomen_organs`
- 生产可跑自动分割模型: `TotalSegmentator`
- 可跑的 prompt 分割模型: `MedSAM2`
- 可跑的 MR 多器官模型: `MRSegmentator`

## MedSAM2 当前状态

`medsam2` 现在已经在 `seg-entry` 中打通，支持：

- 输入类型: `dicom_dir`、`nifti_file`
- 模态: `ct`、`mr`
- prompt 类型: `bbox_2d`、`points_2d`、`diameter_line_2d`
- 标准输出:
  - `liver_tumor.nii.gz`
  - `prompt_plan.json`
  - `prompt_render_primary.png`
  - `prompt_render_index.json`
  - `case.json`
  - `log_path`

其中 `MedSAM2_*.pt` 新权重会优先走本工作区新增的 MedSAM2-compatible runner，而不是旧 `Medical-SAM2` runner。

推荐对 MRI liver lesion 明确传这组参数：

- `medsam2_runner=medsam2_compat`
- `medsam2_ckpt=/mnt/midstorage/user/wya/seg/MedSAM2/checkpoints/MedSAM2_MRI_LiverLesion.pt`
- `medsam2_config=configs/sam2.1_hiera_t512.yaml`
- `medsam2_image_size=512`

如果只传 `medsam2_ckpt=/path/to/MedSAM2_*.pt`，`seg-entry` 也会自动切到新 runner，并把旧的 `sam2_hiera_s` 之类参数归一化到兼容的 MedSAM2 config。

更细的调度说明见：

- [MEDSAM2_POC_DISPATCH_GUIDE.md](/mnt/midstorage/user/wya/seg/seg-entry/MEDSAM2_POC_DISPATCH_GUIDE.md)

## 服务边界

`seg-entry` 只负责分割推理和标准化返回。

- 分割结果只输出 `nii.gz`
- `json` 和 `log` 只是 sidecar 元数据
- 不生成 `SEG`
- 不生成 `RTSTRUCT`

这些事情交给调用端处理。

## 目录结构

```text
seg-entry/
  main.py
  README.md
  examples/
  seg_entry/
    adapters/
    api.py
    cli.py
    contracts.py
    inputs.py
    registry.py
    service.py
```

## 用 uv 管理环境

在项目根目录执行：

```bash
cd /mnt/midstorage/user/wya/seg/seg-entry
uv sync
```

常用命令（都走 `.venv`）：

```bash
uv run python main.py models --pretty
uv run python main.py serve --host 0.0.0.0 --port 8010
```

更新依赖后，记得刷新锁文件：

```bash
uv lock
```

## Docker 化基础模板

项目已提供 `Dockerfile`（多阶段构建）和 `.dockerignore`，可直接构建：

```bash
docker build -t seg-entry:dev .
```

启动服务：

```bash
docker run --rm -p 8010:8010 seg-entry:dev
```

如果要用 GPU（NVIDIA Container Toolkit 已就绪）：

```bash
docker run --rm --gpus all -p 8010:8010 seg-entry:dev
```

## 标准请求示例

### 1. TotalSegmentator 肝脏 CT

```json
{
  "request_id": "demo-liver-ct-001",
  "input_path": "/path/to/dicom_or_nii",
  "input_type": "auto",
  "target": "liver",
  "model": "totalsegmentator",
  "modality": "ct",
  "output_dir": "/tmp/seg-entry-demo/demo-liver-ct-001",
  "engine": {
    "python_bin": "/home/gpu/miniconda3/envs/nnunet_py311/bin/python",
    "device": "gpu",
    "gpu_policy": "auto_best",
    "gpu_candidates": "0,1,2,3,4,5,6,7",
    "gpu_min_free_memory_mb": 4096,
    "quiet": false,
    "overwrite": false,
    "export_mode": "copy",
    "nr_thr_resamp": 1,
    "nr_thr_saving": 1,
    "totalseg_task_profile": "core_liver",
    "totalseg_home": "/mnt/midstorage/user/wya/seg/TotalSegmentator/.totalsegmentator"
  }
}
```

### 2. MedSAM2 MRI liver lesion 示例

```json
{
  "request_id": "demo-liver-medsam2-001",
  "input_path": "/path/to/dicom_or_nii",
  "input_type": "dicom_dir",
  "target": "liver",
  "model": "medsam2",
  "modality": "mr",
  "output_dir": "/tmp/seg-entry-demo/demo-liver-medsam2-001",
  "prompts": [
    {
      "kind": "bbox_2d",
      "frame_index": 9,
      "bbox": [46, 74, 131, 145]
    }
  ],
  "engine": {
    "python_bin": "/home/gpu/miniconda3/envs/medsam2/bin/python",
    "device": "gpu",
    "gpu_policy": "auto_best",
    "gpu_candidates": "0,1,2,3,4,5,6,7",
    "gpu_min_free_memory_mb": 4096,
    "export_mode": "copy",
    "medsam2_runner": "medsam2_compat",
    "medsam2_ckpt": "/mnt/midstorage/user/wya/seg/MedSAM2/checkpoints/MedSAM2_MRI_LiverLesion.pt",
    "medsam2_config": "configs/sam2.1_hiera_t512.yaml",
    "medsam2_image_size": 512
  },
  "metadata": {
    "workflow": {
      "task_preset": "mr_test",
      "model_version": "MedSAM2_MRI_LiverLesion",
      "result_target": "liver_tumor"
    }
  }
}
```

成功后会在 `response.json` 中返回：

- `status=succeeded`
- `primary_artifact=<output_dir>/engine/medsam2/<case_id>/exports/liver_tumor.nii.gz`
- `log_path=<output_dir>/logs/medsam2.log`

并在 `artifacts` 中列出 prompt 计划、prompt 预览图和原生 case summary。

如果你想继续复用旧 `Medical-SAM2` 路线，也可以显式传：

```json
{
  "engine": {
    "medsam2_runner": "medical_sam2_legacy",
    "medsam2_ckpt": "/mnt/midstorage/user/wya/seg/Medical-SAM2/checkpoints/sam2_hiera_small.pt",
    "medsam2_config": "sam2_hiera_s",
    "medsam2_image_size": 1024
  }
}
```

但 `MedSAM2_*.pt` 新权重不要再走这条旧路线。

### 3. MRSegmentator MR 多器官

MRSegmentator 通过自己的 uv 环境和 repo-local 权重运行，不复用
TotalSegmentator 的 Python、runner、home 或 task profile。

```json
{
  "request_id": "demo-mrsegmentator-mr-organs-001",
  "input_path": "/path/to/mr_dicom_series_or_image.nii.gz",
  "input_type": "auto",
  "target": "mr_abdomen_organs",
  "model": "mrsegmentator",
  "modality": "mr",
  "output_dir": "/tmp/seg-entry-demo/demo-mrsegmentator-mr-organs-001",
  "engine": {
    "device": "gpu",
    "gpu_policy": "auto_best",
    "gpu_candidates": "0,1,2,3,4,5,6,7",
    "gpu_min_free_memory_mb": 4096,
    "export_mode": "copy",
    "mrsegmentator_fast": true,
    "mrsegmentator_batchsize": 1,
    "mrsegmentator_nproc": 3,
    "mrsegmentator_nproc_export": 4
  }
}
```

标准示例文件：

```text
examples/request_mrsegmentator_mr_abdomen_organs.json
```

`target=mr_abdomen_organs` 时，主结果是 MRSegmentator 原生多标签：

```text
exports/mrsegmentator_multilabel.nii.gz
```

`target=liver` 时，主结果是二值肝脏 mask：

```text
exports/liver.nii.gz
```

MRSegmentator adapter 还会把 case summary、engine log 和各个非空器官
二值 mask 作为 supporting artifacts 返回。`seg-entry` 不做 DICOM SEG 转换；
多标签 NIfTI 到 multi-segment DICOM SEG 的转换由 `ai-orchestrator` 完成。

## CLI 用法

### 查看模型能力

```bash
python /mnt/midstorage/user/wya/seg/seg-entry/main.py models --pretty
```

### 查看 GPU 状态和自动选卡结果

```bash
python /mnt/midstorage/user/wya/seg/seg-entry/main.py gpu-status --pretty
```

### 直接运行一个 TotalSegmentator 请求

```bash
python /mnt/midstorage/user/wya/seg/seg-entry/main.py run \
  --input-path /path/to/case_or_series \
  --model totalsegmentator \
  --modality ct \
  --output-dir /tmp/seg-entry-demo/request_001 \
  --python-bin /home/gpu/miniconda3/envs/nnunet_py311/bin/python \
  --totalseg-task-profile core_liver \
  --gpu-policy auto_best \
  --gpu-candidates 0,1,2,3,4,5,6,7 \
  --pretty
```

默认行为就是：

- `device=gpu`
- 启动前检查 GPU 状态
- 自动选择最合适的一张卡运行
- `totalseg_task_profile=core_liver`（只导出 `liver.nii.gz`，更快）

### 直接运行一个 MedSAM2 MRI 请求

```bash
python /mnt/midstorage/user/wya/seg/seg-entry/main.py run \
  --request-json /path/to/request.json \
  --pretty
```

或者直接传关键参数：

```bash
python /mnt/midstorage/user/wya/seg/seg-entry/main.py run \
  --input-path /path/to/dicom_series \
  --input-type dicom_dir \
  --model medsam2 \
  --modality mr \
  --prompt-json /path/to/prompts.json \
  --python-bin /home/gpu/miniconda3/envs/medsam2/bin/python \
  --medsam2-runner medsam2_compat \
  --medsam2-ckpt /mnt/midstorage/user/wya/seg/MedSAM2/checkpoints/MedSAM2_MRI_LiverLesion.pt \
  --medsam2-config configs/sam2.1_hiera_t512.yaml \
  --medsam2-image-size 512 \
  --gpu-policy auto_best \
  --gpu-candidates 0,1,2,3,4,5,6,7 \
  --output-dir /tmp/seg-entry-demo/medsam2-request-001 \
  --pretty
```

### 直接运行一个 MRSegmentator MR 多器官请求

```bash
python /mnt/midstorage/user/wya/seg/seg-entry/main.py run \
  --request-json /mnt/midstorage/user/wya/seg/seg-entry/examples/request_mrsegmentator_mr_abdomen_organs.json \
  --pretty
```

或者直接传关键参数：

```bash
python /mnt/midstorage/user/wya/seg/seg-entry/main.py run \
  --input-path /path/to/mr_dicom_series_or_image.nii.gz \
  --input-type auto \
  --model mrsegmentator \
  --target mr_abdomen_organs \
  --modality mr \
  --gpu-policy auto_best \
  --gpu-candidates 0,1,2,3,4,5,6,7 \
  --output-dir /tmp/seg-entry-demo/mrsegmentator-organs-001 \
  --pretty
```

默认会使用：

- `MRSegmentator/.venv/bin/python`
- `MRSegmentator/scripts/run_liver_workflow.py`
- `MRSegmentator/weights`
- `mrsegmentator_fast=true`

如果你想手工指定 GPU：

```bash
python /mnt/midstorage/user/wya/seg/seg-entry/main.py run \
  --input-path /path/to/case_or_series \
  --model totalsegmentator \
  --modality ct \
  --gpu-policy manual \
  --gpu-id 3 \
  --pretty
```

### 用 JSON 文件运行

```bash
python /mnt/midstorage/user/wya/seg/seg-entry/main.py run \
  --request-json /mnt/midstorage/user/wya/seg/seg-entry/examples/request_totalseg_liver_ct.json \
  --pretty
```

## HTTP 用法

启动服务：

```bash
python /mnt/midstorage/user/wya/seg/seg-entry/main.py serve --host 0.0.0.0 --port 8010
```

接口：

- `GET /health`
- `GET /models`
- `GET /runtime/gpus`
- `POST /segmentations`

示例：

```bash
curl -X POST http://127.0.0.1:8010/segmentations \
  -H 'Content-Type: application/json' \
  -d @/mnt/midstorage/user/wya/seg/seg-entry/examples/request_totalseg_liver_ct.json
```

## 标准输出

每次请求都会生成：

```text
<output_dir>/
  request.json
  response.json
  plans/
  logs/
  engine/
```

其中：

- `request.json` 是归档后的标准请求
- `response.json` 是标准返回
- `engine/` 保存模型原生输出
- `logs/` 保存引擎日志

注意：

- 所有分割掩码都必须是 `nii.gz`
- 这层服务不考虑 `SEG`

对于 `TotalSegmentator` 肝脏 CT，`response.json` 里会标准化返回：

- 当 `engine.totalseg_task_profile=core_liver`（默认）时：`liver.nii.gz`
- 当 `engine.totalseg_task_profile=full_liver` 时：`liver.nii.gz`、`liver_vessels.nii.gz`、`liver_tumor.nii.gz`、`liver_segment_1.nii.gz` 到 `liver_segment_8.nii.gz`

对于 `TotalSegmentator` 肝脏 MR，返回：

- 当 `engine.totalseg_task_profile=core_liver`（默认）时：`liver.nii.gz`
- 当 `engine.totalseg_task_profile=full_liver` 时：`liver.nii.gz`、`liver_segment_1.nii.gz` 到 `liver_segment_8.nii.gz`

对于 `MRSegmentator` MR 多器官，返回：

- `target=mr_abdomen_organs`：`mrsegmentator_multilabel.nii.gz` 作为主结果
- `target=liver`：`liver.nii.gz` 作为主结果
- 非空器官二值 mask、`case.json` 和 `mrsegmentator.log` 作为辅助产物

## 推荐的 Orthanc 对接方式

推荐后续直接把 Orthanc 对接到这个 HTTP 接口：

1. Orthanc 导出一组 DICOM 到本地临时目录
2. 调用 `POST /segmentations`
3. 读取 `response.json` 或 HTTP 返回体里的主结果路径
4. 调用端自己决定后续是否转 `SEG` 或进入下一步处理

这样 Orthanc 侧不需要理解 TotalSegmentator 或 MedSAM2 的内部细节，只认标准请求/响应即可。
