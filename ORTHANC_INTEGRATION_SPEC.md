# Orthanc Integration Spec

本文档定义 Orthanc 调用 `seg-entry` 的接口协议。  
目标是让 Orthanc 侧严格按协议组装请求，而不是自由发挥。

协议版本:

- `orthanc-seg-entry-v1`

适用范围:

- 当前目标器官: `liver`
- 当前生产模型: `totalsegmentator`
- 当前输入方式: 本地 DICOM 序列目录

## 职责边界

Orthanc 负责：

- 选择要分割的影像序列
- 将该序列导出到本地临时目录
- 组装标准 JSON 请求
- 调用 `POST /segmentations`
- 消费返回的 `nii.gz` 路径
- 后续自行决定是否转 `SEG`

`seg-entry` 负责：

- 接收请求
- 执行分割
- 返回标准化 `nii.gz` 分割结果
- 返回日志、原生输出目录和执行元数据

`seg-entry` 不负责：

- 直接生成 DICOM SEG
- 回写 Orthanc
- 管理 Orthanc 内部任务队列

## HTTP 接口

服务地址示例：

- `http://127.0.0.1:8010`

本次对接只需要关心：

- `POST /segmentations`
- `GET /health`
- `GET /models`
- `GET /runtime/gpus`

## 调用模式

当前版本是同步接口。

含义：

- Orthanc 发起 `POST /segmentations`
- 请求会阻塞直到分割完成或失败
- 一个肝脏 CT 请求可能需要数分钟

所以 Orthanc 侧必须：

- 用后台任务或服务端脚本调用
- 配置足够长的 HTTP 超时
- 不要走前端短超时链路

## 输入目录要求

Orthanc 在调用前必须先把目标序列导出到本地目录。

要求：

- `input_path` 必须是绝对路径
- 目录里只能放一个影像序列的切片
- 不要混入别的 series
- 不要传 Orthanc 内部 URL
- 不要传单个 DICOM 文件

推荐结构：

```text
/tmp/orthanc-export/
  <request_id>/
    dicom/
      1.dcm
      2.dcm
      3.dcm
      ...
```

## Orthanc 必填请求字段

以下字段必须由 Orthanc 组装：

| 字段 | 类型 | 是否必填 | 说明 |
|---|---|---|---|
| `request_id` | `string` | 是 | 全局唯一请求号，建议 Orthanc 生成 |
| `input_path` | `string` | 是 | 本地 DICOM 序列目录绝对路径 |
| `input_type` | `string` | 是 | 固定传 `dicom_dir` |
| `target` | `string` | 是 | 当前固定传 `liver` |
| `model` | `string` | 是 | 当前固定传 `totalsegmentator` |
| `modality` | `string` | 是 | `ct` 或 `mr` |
| `output_dir` | `string` | 是 | 分割结果输出根目录绝对路径 |

## Orthanc 推荐请求字段

推荐加上：

| 字段 | 类型 | 是否推荐 | 说明 |
|---|---|---|---|
| `engine.device` | `string` | 是 | 推荐固定传 `gpu` |
| `engine.gpu_policy` | `string` | 是 | 推荐固定传 `auto_best` |
| `engine.gpu_candidates` | `string` | 是 | 推荐传 `0,1,2,3,4,5,6,7` |
| `engine.gpu_min_free_memory_mb` | `int` | 是 | 推荐传 `4096` |
| `engine.totalseg_task_profile` | `string` | 是 | 推荐传 `core_liver`，只输出主肝脏掩码并减少耗时 |
| `engine.python_bin` | `string` | 否 | 推荐按部署环境写死 |
| `engine.totalseg_home` | `string` | 否 | 推荐按部署环境写死 |
| `metadata` | `object` | 是 | 推荐回传 Orthanc 业务上下文 |

## 推荐的 metadata 结构

`seg-entry` 不强校验 `metadata`，但 Orthanc 应按下面结构传，方便审计和后续排障：

```json
{
  "source_system": "orthanc",
  "orthanc": {
    "instance_id": "optional",
    "patient_id": "optional",
    "study_instance_uid": "required_recommended",
    "series_instance_uid": "required_recommended",
    "study_id": "optional",
    "series_description": "optional",
    "accession_number": "optional"
  },
  "business": {
    "tenant_id": "optional",
    "project_code": "optional",
    "operator": "optional"
  }
}
```

推荐至少传：

- `metadata.source_system`
- `metadata.orthanc.study_instance_uid`
- `metadata.orthanc.series_instance_uid`

## Orthanc 标准请求示例

```json
{
  "request_id": "orthanc-liver-ct-20260319-0001",
  "input_path": "/tmp/orthanc-export/orthanc-liver-ct-20260319-0001/dicom",
  "input_type": "dicom_dir",
  "target": "liver",
  "model": "totalsegmentator",
  "modality": "ct",
  "output_dir": "/tmp/orthanc-seg-out/orthanc-liver-ct-20260319-0001",
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
  },
  "metadata": {
    "source_system": "orthanc",
    "orthanc": {
      "study_instance_uid": "1.2.840.xxx.study",
      "series_instance_uid": "1.2.840.xxx.series",
      "series_description": "Abdomen CT"
    }
  }
}
```

仓库里的示例文件：

- [request_orthanc_totalseg_liver_ct.json](/mnt/midstorage/user/wya/seg/seg-entry/examples/request_orthanc_totalseg_liver_ct.json)

## 成功响应中 Orthanc 需要重点读取的字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | `string` | 成功时必须是 `succeeded` |
| `primary_artifact` | `string` | 主分割结果路径，当前是 `liver.nii.gz` |
| `artifacts` | `array` | 全部可消费产物 |
| `output_dir` | `string` | 本次请求的归档目录 |
| `native_output_dir` | `string` | 原生引擎输出目录 |
| `log_path` | `string` | 引擎日志路径 |
| `metadata.execution.gpu_selection` | `object` | 实际选中的 GPU 信息 |

## 成功响应约束

Orthanc 必须按下面理解成功结果：

- `primary_artifact` 是主输出
- `artifacts` 中 `role=primary_mask` 或 `role=supporting_mask` 的分割结果全部是 `nii.gz`
- `json` 和 `log` 只是 sidecar 元数据
- 不要期待服务端直接返回 `SEG`

## 失败响应约束

如果失败，Orthanc 必须至少读取：

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | `string` | 失败时为 `failed` |
| `error.code` | `string` | 机器可判定错误码 |
| `error.message` | `string` | 人类可读错误信息 |
| `output_dir` | `string` | 失败请求归档目录 |

常见错误码：

- `input_not_found`
- `invalid_output_dir`
- `unsupported_model`
- `unsupported_target`
- `modality_required`
- `gpu_probe_failed`
- `gpu_capacity_insufficient`
- `totalseg_run_failed`

## Orthanc 成功判定规则

Orthanc 侧不要只看 HTTP 200。

必须同时满足：

1. HTTP 状态码是 `200`
2. 返回体里的 `status == "succeeded"`
3. `primary_artifact` 非空
4. `primary_artifact` 指向本地存在的 `nii.gz`

## Orthanc 失败判定规则

以下任一情况都视为失败：

1. HTTP 状态码 `>= 400`
2. 返回体 `status != "succeeded"`
3. `primary_artifact` 为空
4. 输出文件不存在

## Orthanc 最小实现清单

Orthanc 对接方至少要实现：

1. 导出单一 DICOM 序列到本地目录
2. 生成唯一 `request_id`
3. 严格按本文档组装 JSON
4. 以后台任务方式调用 `POST /segmentations`
5. 检查成功判定规则
6. 消费 `primary_artifact` 和 `artifacts`
7. 自己决定后续是否转 `SEG`

## 当前不建议 Orthanc 侧做的事

当前不要让 Orthanc 直接组装 MedSAM2 请求，因为 prompt 来源还没冻结。

也不要让 Orthanc 假设：

- 服务一定返回 DICOM
- 服务一定是异步接口
- 服务会自己回写 Orthanc

## 结论

给 Orthanc 的一句话要求可以直接写成：

“Orthanc 必须先把单个影像序列导出到本地 DICOM 目录，再按 `orthanc-seg-entry-v1` 协议调用 `POST /segmentations`，并只消费返回的 `nii.gz` 分割结果；SEG 转换属于调用端职责，不属于 seg-entry 服务职责。”
