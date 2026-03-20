# seg-entry 研发接口说明

这份文档面向研发同学，目标是回答 3 个最常见的问题：

- 请求里的每个参数是什么意思，什么时候填
- CLI 命令行参数和 JSON 请求体是什么对应关系
- 返回结果里的每个字段、每个分割文件分别代表什么

当前版本范围：

- 目标器官：`liver`
- 可生产运行模型：`totalsegmentator`
- 预留模型：`medsam2`
- 分割输出格式：只支持 `nii.gz`

## 1. 一句话理解接口

`seg-entry` 的职责很单纯：

- 输入一份影像数据
- 指定要做什么分割
- 指定用哪个模型
- 返回标准化的分割结果和元数据

它不是阅片系统，也不是 DICOM SEG 转换器。

## 2. 你最常用的调用方式

如果你是本地手工测试，最推荐直接用 CLI：

```bash
python /mnt/midstorage/user/wya/seg/seg-entry/main.py run \
  --request-id manual-test-0000106056 \
  --input-path /mnt/midstorage/user/wya/seg/data_qyl/ori_nii/0000106056_2.0-x-2.0_V_2mm_0000.nii.gz \
  --input-type nifti_file \
  --model totalsegmentator \
  --target liver \
  --modality ct \
  --output-dir /mnt/midstorage/user/wya/seg/test/manual-test-0000106056 \
  --python-bin /home/gpu/miniconda3/envs/nnunet_py311/bin/python \
  --gpu-policy auto_best \
  --gpu-candidates 0,1,2,3,4,5,6,7 \
  --pretty
```

如果这份数据不是 CT，而是 MR，只改这一项：

```bash
--modality mr
```

## 3. 请求字段说明

标准请求体长这样：

```json
{
  "request_id": "manual-test-0000106056",
  "input_path": "/path/to/case.nii.gz",
  "input_type": "nifti_file",
  "target": "liver",
  "model": "totalsegmentator",
  "modality": "ct",
  "output_dir": "/path/to/output",
  "prompts": [],
  "engine": {
    "python_bin": "/home/gpu/miniconda3/envs/nnunet_py311/bin/python",
    "device": "gpu",
    "gpu_policy": "auto_best",
    "gpu_candidates": "0,1,2,3,4,5,6,7",
    "gpu_id": null,
    "gpu_min_free_memory_mb": 4096,
    "quiet": false,
    "overwrite": false,
    "export_mode": "copy",
    "nr_thr_resamp": 1,
    "nr_thr_saving": 1,
    "totalseg_task_profile": "core_liver"
  },
  "metadata": {}
}
```

### 3.1 顶层字段

#### `request_id`

作用：

- 这次请求的唯一标识
- 会出现在输出目录、日志、响应里

怎么填：

- 推荐人工可读，比如 `manual-test-0000106056`
- 只能理解为“这次任务编号”，不是病人 ID

不填会怎样：

- 服务会自动生成，例如 `20260319-101530-ab12cd34`

推荐：

- 研发联调用手工命名
- 线上对接可由调用方生成全局唯一值

#### `input_path`

作用：

- 输入影像的路径

支持值：

- 单个 `nii` 或 `nii.gz` 文件
- 一个 DICOM 序列目录

当前你的例子：

```text
/mnt/midstorage/user/wya/seg/data_qyl/ori_nii/0000106056_2.0-x-2.0_V_2mm_0000.nii.gz
```

这是必填项。

#### `input_type`

作用：

- 告诉服务输入到底是什么类型

可选值：

- `auto`
- `nifti_file`
- `dicom_dir`

怎么理解：

- `auto`：服务自己判断
- `nifti_file`：你明确告诉它这是一个 `nii/nii.gz`
- `dicom_dir`：你明确告诉它这是一个 DICOM 目录

推荐：

- 手工测试时尽量写明确，不要依赖 `auto`
- NIfTI 就写 `nifti_file`
- DICOM 目录就写 `dicom_dir`

#### `target`

作用：

- 指定要分割什么目标

当前可选值：

- `liver`

现阶段它几乎是固定值，先这样理解就行。

#### `model`

作用：

- 指定使用哪个分割模型

当前可选值：

- `totalsegmentator`
- `medsam2`

当前建议：

- 生产和手工测试都优先用 `totalsegmentator`
- `medsam2` 目前只是接口预留，未来需要附加 prompt

#### `modality`

作用：

- 指定影像模态

当前可选值：

- `ct`
- `mr`

为什么需要它：

- `TotalSegmentator` 的肝脏流程会根据模态决定运行哪条 workflow
- 不同模态返回的附加分割文件也不完全一样

怎么填：

- CT 就填 `ct`
- MR 就填 `mr`

如果填错会怎样：

- 轻则走错 workflow
- 重则结果不可靠，甚至直接失败

结论：

- 这是一个业务语义字段，不是可有可无的备注

#### `output_dir`

作用：

- 指定这次请求的输出目录

服务会在这个目录下写入：

- `request.json`
- `response.json`
- `engine/`
- `logs/`
- `plans/`

推荐：

- 每次请求用一个独立目录
- 不要多个请求共用同一个输出目录

#### `prompts`

作用：

- 给 prompt-based 模型传附加提示信息

当前状态：

- `totalsegmentator` 不需要，通常传空数组 `[]`
- `medsam2` 未来需要

如果你现在做 TotalSegmentator：

```json
"prompts": []
```

就可以。

#### `metadata`

作用：

- 调用方自带的业务附加信息

典型用途：

- 传病人号
- 传 study/series 标识
- 传 Orthanc 的内部 ID

注意：

- 这个字段不会影响分割算法本身
- 它只是为了链路追踪和对账

### 3.2 `engine` 字段

`engine` 是“怎么跑模型”的配置，不是“分割什么”的业务配置。

#### `engine.python_bin`

作用：

- 运行模型时使用的 Python 解释器

什么时候填：

- 建议显式填写
- 尤其是 TotalSegmentator 依赖固定环境时

典型值：

```text
/home/gpu/miniconda3/envs/nnunet_py311/bin/python
```

#### `engine.device`

作用：

- 指定使用 GPU 还是 CPU

可选值：

- `gpu`
- `cpu`

当前建议：

- 默认使用 `gpu`

#### `engine.gpu_policy`

作用：

- 决定如何选择 GPU

可选值：

- `auto_best`
- `manual`

怎么理解：

- `auto_best`：服务启动前自动检查 GPU 状态，选最合适的一张卡
- `manual`：你手工指定某一张 GPU

推荐：

- 大多数场景用 `auto_best`

#### `engine.gpu_candidates`

作用：

- 指定自动选卡时允许参与竞争的 GPU 列表

格式：

```text
0,1,2,3,4,5,6,7
```

怎么理解：

- 不是最终一定用这些卡全部运行
- 而是说“从这些卡里面挑一张最合适的”

#### `engine.gpu_id`

作用：

- 当 `gpu_policy=manual` 时，指定具体 GPU 编号

例子：

```json
"gpu_policy": "manual",
"gpu_id": 3
```

如果 `gpu_policy=auto_best`：

- 这个字段一般不填

#### `engine.gpu_min_free_memory_mb`

作用：

- 自动选卡时，要求候选 GPU 至少有多少空闲显存

默认值：

- `4096`

怎么理解：

- 小于这个值的卡会被过滤掉
- 防止挑到已经快满的卡

#### `engine.quiet`

作用：

- 减少底层引擎打印日志

一般：

- 调试时填 `false`
- 批量跑任务时可以考虑 `true`

#### `engine.overwrite`

作用：

- 如果输出目录里已经有旧产物，是否允许覆盖

风险：

- 打开后可能覆盖旧结果

建议：

- 联调阶段默认 `false`
- 明确需要重跑时再开 `true`

#### `engine.export_mode`

作用：

- 标准产物导出时采用复制还是软链接

可选值：

- `copy`
- `symlink`

推荐：

- 默认 `copy`

说明：

- `copy` 更稳妥，便于后续独立搬运结果
- `symlink` 节省空间，但对目录搬迁更敏感

#### `engine.nr_thr_resamp`

作用：

- 底层引擎重采样线程数

#### `engine.nr_thr_saving`

作用：

- 底层引擎保存线程数

当前建议：

- 先保持默认值 `1`
- 这两个字段主要给性能调优使用

#### `engine.totalseg_task_profile`

作用：

- 控制 TotalSegmentator 到底跑“只要主肝脏”还是“全量肝脏族”

可选值：

- `core_liver`
- `full_liver`

怎么理解：

- `core_liver`：只输出 `liver.nii.gz`，通常更快，适合绝大多数“只要肝脏轮廓”的场景
- `full_liver`：额外输出肝血管、肝肿瘤、Couinaud 肝段，耗时更长

推荐：

- 默认用 `core_liver`
- 仅在业务明确需要肝段/血管/肿瘤时才切 `full_liver`

## 4. CLI 参数和 JSON 字段怎么对应

最常用映射如下：

- `--request-id` 对应 `request_id`
- `--input-path` 对应 `input_path`
- `--input-type` 对应 `input_type`
- `--target` 对应 `target`
- `--model` 对应 `model`
- `--modality` 对应 `modality`
- `--output-dir` 对应 `output_dir`
- `--python-bin` 对应 `engine.python_bin`
- `--device` 对应 `engine.device`
- `--gpu-policy` 对应 `engine.gpu_policy`
- `--gpu-candidates` 对应 `engine.gpu_candidates`
- `--gpu-id` 对应 `engine.gpu_id`
- `--gpu-min-free-memory-mb` 对应 `engine.gpu_min_free_memory_mb`
- `--quiet` 对应 `engine.quiet`
- `--overwrite` 对应 `engine.overwrite`
- `--export-mode` 对应 `engine.export_mode`
- `--nr-thr-resamp` 对应 `engine.nr_thr_resamp`
- `--nr-thr-saving` 对应 `engine.nr_thr_saving`
- `--totalseg-task-profile` 对应 `engine.totalseg_task_profile`

所以：

- 命令行调用，本质上就是在临时拼一份 JSON 请求
- `--request-json` 则是直接把完整 JSON 喂给服务

## 5. 什么参数是必填，什么参数可以不填

### 5.1 TotalSegmentator 当前最小可用集合

如果你要跑 `totalsegmentator`，最少建议明确写这几个：

- `input_path`
- `input_type`
- `model`
- `target`
- `modality`
- `output_dir`

其中真正严格意义上的硬必填是：

- `input_path`

但从业务正确性角度，下面这些也应该视为必填：

- `model`
- `target`
- `modality`
- `output_dir`

### 5.2 可以省略、由系统兜底的字段

- `request_id`
- `input_type`
- `engine.device`
- `engine.gpu_policy`
- `engine.gpu_candidates`
- `engine.gpu_min_free_memory_mb`

但是研发接入时仍然建议写清楚，避免“依赖默认值但没人知道默认值是什么”。

## 6. 返回结果说明

每次调用结束后，输出目录下一定会有：

```text
<output_dir>/
  request.json
  response.json
  plans/
  logs/
  engine/
```

### 6.1 `request.json`

含义：

- 归档后的请求参数

用途：

- 复盘这次任务到底怎么跑的
- 排查“为什么这次和上次结果不一样”

### 6.2 `response.json`

含义：

- 标准返回体

它是最重要的文件，调用方后续应该优先读取它，而不是自己去猜目录结构。

## 7. `response.json` 字段逐项解释

一个成功响应大致长这样：

```json
{
  "request_id": "manual-test-0000106056",
  "status": "succeeded",
  "model": "totalsegmentator",
  "target": "liver",
  "input_path": "/path/to/case.nii.gz",
  "input_type": "nifti_file",
  "modality": "ct",
  "output_dir": "/path/to/output",
  "artifacts": [],
  "primary_artifact": "/path/to/output/engine/totalsegmentator/manual-test-0000106056/exports/liver.nii.gz",
  "native_output_dir": "/path/to/output/engine/totalsegmentator/manual-test-0000106056",
  "log_path": "/path/to/output/logs/totalsegmentator.log",
  "timings": {
    "started_at_epoch": 0,
    "finished_at_epoch": 0,
    "duration_sec": 0
  },
  "metadata": {},
  "error": null
}
```

### 7.1 顶层状态字段

#### `status`

可选值：

- `succeeded`
- `failed`

调用方的第一判断条件就是看它。

#### `primary_artifact`

作用：

- 这次请求最核心的主结果路径

对于肝脏分割来说，它就是：

- `liver.nii.gz`

调用方如果只需要“主肝脏掩码”，优先读这个字段。

#### `artifacts`

作用：

- 返回所有产物的清单

每个元素包含：

- `name`：产物逻辑名
- `role`：产物角色
- `path`：绝对路径
- `format`：文件格式
- `description`：给研发/调用方看的说明

### 7.2 `artifacts[].role` 的含义

当前常见角色有：

- `primary_mask`：主分割结果
- `supporting_mask`：附加分割结果
- `native_metadata`：模型原生元数据
- `native_log`：模型运行日志

你可以这样理解：

- 真正的分割 `nii.gz` 看 `primary_mask` 和 `supporting_mask`
- 调试排障看 `native_metadata` 和 `native_log`

### 7.3 `native_output_dir`

作用：

- 底层模型原生输出目录

用途：

- 排查引擎行为
- 查看模型生成的原始中间文件

研发对接时：

- 正常业务流程不建议依赖它
- 它更偏排障字段

### 7.4 `log_path`

作用：

- 底层模型日志路径

什么时候看它：

- 请求失败
- 结果不符合预期
- 要定位 TotalSegmentator 原生报错

### 7.5 `timings`

字段：

- `started_at_epoch`
- `finished_at_epoch`
- `duration_sec`

作用：

- 记录本次任务耗时

### 7.6 `metadata`

当前 `totalsegmentator` 成功时，里面通常会包含：

- `engine`
- `engine_case_id`
- `engine_summary`
- `prompt_policy`
- `execution`

其中最值得研发关注的是：

- `metadata.execution.device`
- `metadata.execution.gpu_selection`

因为这能说明这次到底是 CPU 还是 GPU 跑的，以及最终选中了哪张卡。

### 7.7 `error`

成功时：

- `null`

失败时：

- 是一个结构化错误对象

调用方应该：

- 先看 `status`
- 如果是 `failed`，再读取 `error.code`、`error.message`、`error.details`

## 8. TotalSegmentator 肝脏结果里，每个文件分别是什么

### 8.1 CT 模式

当 `engine.totalseg_task_profile=core_liver`（默认）时：

- `liver.nii.gz`

当 `engine.totalseg_task_profile=full_liver` 时，返回：

- `liver.nii.gz`
- `liver_vessels.nii.gz`
- `liver_tumor.nii.gz`
- `liver_segment_1.nii.gz`
- `liver_segment_2.nii.gz`
- `liver_segment_3.nii.gz`
- `liver_segment_4.nii.gz`
- `liver_segment_5.nii.gz`
- `liver_segment_6.nii.gz`
- `liver_segment_7.nii.gz`
- `liver_segment_8.nii.gz`

含义：

- `liver.nii.gz`：主肝脏整体掩码
- `liver_vessels.nii.gz`：肝血管相关掩码
- `liver_tumor.nii.gz`：肝肿瘤相关掩码
- `liver_segment_1` 到 `8`：Couinaud 肝段分区掩码

如果你的业务只需要“肝脏整体分割”：

- 只取 `primary_artifact`
- 或只取 `artifacts` 里 `role=primary_mask` 的那一个

### 8.2 MR 模式

当 `engine.totalseg_task_profile=core_liver`（默认）时：

- `liver.nii.gz`

当 `engine.totalseg_task_profile=full_liver` 时，返回：

- `liver.nii.gz`
- `liver_segment_1.nii.gz`
- `liver_segment_2.nii.gz`
- `liver_segment_3.nii.gz`
- `liver_segment_4.nii.gz`
- `liver_segment_5.nii.gz`
- `liver_segment_6.nii.gz`
- `liver_segment_7.nii.gz`
- `liver_segment_8.nii.gz`

和 CT 相比，当前标准里没有：

- `liver_vessels.nii.gz`
- `liver_tumor.nii.gz`

## 9. 研发最常见的填写建议

### 场景 1：本地手工测一个 NIfTI

建议填写：

- `input_path`：NIfTI 文件绝对路径
- `input_type`：`nifti_file`
- `model`：`totalsegmentator`
- `target`：`liver`
- `modality`：`ct` 或 `mr`
- `output_dir`：单独测试目录

### 场景 2：Orthanc 导出一个 DICOM 序列后调用

建议填写：

- `input_path`：导出的 DICOM 目录
- `input_type`：`dicom_dir`
- 其他字段同上

### 场景 3：调用方只关心最终主掩码

调用后只读：

- `status`
- `primary_artifact`

### 场景 4：调用方还想拿附加结果

调用后遍历：

- `artifacts`

按照 `name` 或 `role` 取你要的文件。

## 10. 一个完整的研发示例

### 10.1 CLI 版本

```bash
python /mnt/midstorage/user/wya/seg/seg-entry/main.py run \
  --request-id manual-test-0000106056 \
  --input-path /mnt/midstorage/user/wya/seg/data_qyl/ori_nii/0000106056_2.0-x-2.0_V_2mm_0000.nii.gz \
  --input-type nifti_file \
  --model totalsegmentator \
  --target liver \
  --modality ct \
  --output-dir /mnt/midstorage/user/wya/seg/test/manual-test-0000106056 \
  --python-bin /home/gpu/miniconda3/envs/nnunet_py311/bin/python \
  --gpu-policy auto_best \
  --gpu-candidates 0,1,2,3,4,5,6,7 \
  --pretty
```

### 10.2 JSON 请求版本

```json
{
  "request_id": "manual-test-0000106056",
  "input_path": "/mnt/midstorage/user/wya/seg/data_qyl/ori_nii/0000106056_2.0-x-2.0_V_2mm_0000.nii.gz",
  "input_type": "nifti_file",
  "target": "liver",
  "model": "totalsegmentator",
  "modality": "ct",
  "output_dir": "/mnt/midstorage/user/wya/seg/test/manual-test-0000106056",
  "prompts": [],
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
    "totalseg_task_profile": "core_liver"
  },
  "metadata": {
    "source": "manual_test"
  }
}
```

## 11. 失败时应该怎么判断

先看 `response.json`：

- `status=succeeded`：成功
- `status=failed`：失败

失败时重点看：

- `error.code`
- `error.message`
- `error.details`
- `log_path`

典型错误包括：

- `missing_field`
- `unsupported_model`
- `unsupported_target`
- `modality_required`
- `invalid_input_type`
- `cannot_infer_input_type`
- `invalid_output_dir`
- `totalseg_run_failed`

## 12. 给研发的最简消费规则

如果你要把这套服务对接到别的系统，最推荐遵守这 4 条：

1. 调用前明确写 `input_type`、`model`、`target`、`modality`
2. 每次请求使用独立 `output_dir`
3. 成功后优先读取 `response.json`，不要硬编码猜目录
4. 如果只需要主肝脏结果，只消费 `primary_artifact`

## 13. 当前版本的边界

这版明确不做：

- DICOM SEG 输出
- RTSTRUCT 输出
- 队列调度
- 异步任务系统
- MedSAM2 生产执行

这版明确会做的事情只有：

- 接收标准请求
- 调用标准模型
- 返回标准 `nii.gz` 分割结果
