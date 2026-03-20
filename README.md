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

- 目标器官: `liver`
- 生产可跑模型: `TotalSegmentator`
- 预留接口模型: `MedSAM2`

## 为什么 MedSAM2 先不直接打通

MedSAM2 不是“只给图像就出结果”的模型，它依赖额外 prompt，比如：

- 某一层的 `bbox`
- 某一层的 `points`
- `frame_index` / 关键切片

这意味着如果上游还没有把 prompt 的来源定好，比如：

- Orthanc 前端手工框选
- 测量线/标注转换
- 其他模型先粗分割后自动生成 prompt

那现在直接把 MedSAM2 做成生产入口，后面大概率会返工。

所以这一版做法是：

- 在标准请求协议里正式纳入 `prompts`
- 在模型注册里把 `medsam2` 标记为 `planned`
- 先让 `TotalSegmentator` 作为稳定生产入口

这样未来要接 MedSAM2 时，只是补一个适配器实现，不用改总入口协议。

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
    cli.py
    contracts.py
    http_server.py
    inputs.py
    registry.py
    service.py
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

### 2. MedSAM2 未来协议示例

```json
{
  "request_id": "demo-liver-medsam2-001",
  "input_path": "/path/to/case.nii.gz",
  "input_type": "nifti_file",
  "target": "liver",
  "model": "medsam2",
  "modality": "ct",
  "output_dir": "/tmp/seg-entry-demo/demo-liver-medsam2-001",
  "prompts": [
    {
      "kind": "bbox_2d",
      "frame_index": 87,
      "bbox": [160, 120, 350, 320]
    }
  ]
}
```

当前如果你传 `model=medsam2`，接口会明确告诉你：

- prompt 协议已经准备好
- 但 runnable engine hook 还没有正式启用

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

## 推荐的 Orthanc 对接方式

推荐后续直接把 Orthanc 对接到这个 HTTP 接口：

1. Orthanc 导出一组 DICOM 到本地临时目录
2. 调用 `POST /segmentations`
3. 读取 `response.json` 或 HTTP 返回体里的主结果路径
4. 调用端自己决定后续是否转 `SEG` 或进入下一步处理

这样 Orthanc 侧不需要理解 TotalSegmentator 或 MedSAM2 的内部细节，只认标准请求/响应即可。
