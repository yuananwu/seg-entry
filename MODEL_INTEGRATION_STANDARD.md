# Model Integration Standard

本文件定义 `seg-entry` 后续所有模型接入都必须遵守的框架和规矩。

标准版本:

- `seg-entry-model-standard-v1`

## 服务边界

`seg-entry` 是一个解耦出来的分割服务，不负责：

- DICOM SEG
- RTSTRUCT
- PACS/Orthanc 回写
- 浏览器标注前端

`seg-entry` 负责：

- 接收标准化分割请求
- 调度具体模型
- 返回标准化的 `nii.gz` 分割结果
- 输出请求归档、响应归档、日志和原生模型元数据

## 强制输出约束

所有模型适配器都必须满足：

- 主分割结果必须是 `nii.gz`
- 辅助分割结果也必须是 `nii.gz`
- 允许存在 sidecar 文件，但仅限：
  - `json`
  - `log`

不允许模型适配器直接输出：

- `dicom_seg`
- `rtstruct`
- 任何依赖调用端业务协议的回写格式

## 模型适配器目录规范

新增模型时必须落在：

```text
seg_entry/adapters/<model_name>.py
```

并且必须在：

- `seg_entry/registry.py`

里注册。

## 适配器必须声明的 capability

每个模型适配器必须显式声明：

- `name`
- `status`
- `targets`
- `input_types`
- `supported_modalities`
- `prompt_required`
- `prompt_kinds`
- `service_contract_version`
- `segmentation_output_format`
- `sidecar_formats`
- `notes`

## 适配器必须实现的代码约束

每个适配器都必须实现：

1. `validate_request(request)`
2. `run(request, context)`

## 请求校验最低要求

每个模型至少要校验：

- `target` 是否支持
- `input_type` 是否支持
- `modality` 是否支持
- prompt 是否必填
- prompt 类型是否合法
- 关键运行参数是否完整

## GPU 运行标准

默认策略：

- `device = gpu`
- `gpu_policy = auto_best`

含义：

- 接口调用时默认走 GPU
- 启动前先探测 GPU 状态
- 从候选卡中选择一张最适合当前任务的卡

当前自动选卡依据：

1. `memory_free_mb` 越大越优先
2. `utilization_gpu_pct` 越低越优先
3. `memory_used_mb` 越低越优先
4. `gpu index` 越小越优先

必须支持的运行模式：

- `auto_best`
- `manual`
- `cpu`

## 日志和可追踪性要求

每次请求必须落地：

- `request.json`
- `response.json`
- `logs/`
- `engine/`

返回元数据里必须尽量包含：

- 实际模型名
- 原生输出目录
- 关键日志路径
- GPU 选择结果
- 原生任务摘要

## 接入新模型的 checklist

1. 新建适配器文件
2. 声明 capability
3. 实现 `validate_request`
4. 实现 `run`
5. 确保所有分割结果输出为 `nii.gz`
6. 不输出 SEG/RTSTRUCT
7. 在 `registry.py` 注册
8. 更新 `README.md`
9. 增加一个最小可运行示例请求
10. 做一次 smoke test

## MedSAM2 这类 prompt 模型的额外要求

对 prompt 型模型，还必须额外明确：

- prompt 来源
- prompt 坐标系
- prompt 所属切片
- prompt 与输入重采样之间的映射关系

如果这些前提还没定清楚，不允许直接宣称进入 production。
