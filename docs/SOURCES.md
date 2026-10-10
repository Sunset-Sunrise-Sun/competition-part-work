# 参考资料与查阅记录

核对日期：2026-10-09。以下仅列支持对应事实的官方／原始资料，不代表推荐最新版本。赛事后续通知可能更新要求。

| 资料 | 用途 |
|---|---|
| [赛事官网](https://www.oschina.net/oa2026/) | 赛道、主体、材料、时间、评分 |
| [MediaPipe Pose Web](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/web_js) | 33 关键点、JS、视频、Worker |
| [MediaPipe Face Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker) | 人脸技术背景，不证明疲劳识别 |
| [ONNX Runtime Web](https://onnxruntime.ai/docs/tutorials/web/) | WASM、WebGPU 等端侧选项及限制 |
| [Compendium](https://pacompendium.com/) | MET 定义 |
| [2024 成人活动表](https://pacompendium.com/adult-compendium/) | 活动类别与 MET 来源候选 |
| [Corrected METs](https://pacompendium.com/corrected-mets/) | 个体估算限制，不能替代直接测量 |
| [whisper.cpp WASM](https://github.com/ggml-org/whisper.cpp/blob/master/examples/whisper.wasm/README.md) | 本地浏览器语音候选 |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | 本地量化推理与 API |
| [Qwen3-4B 模型卡](https://huggingface.co/Qwen/Qwen3-4B) | 模型规格与许可候选 |
| [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) | 有状态编排与确定性／模型混合 |
| [USDA FoodData Central](https://fdc.nal.usda.gov/api-guide/) | 食品数据库候选，不代表中国菜完整覆盖 |
| [WHO Healthy diet](https://www.who.int/news-room/fact-sheets/detail/healthy-diet) | 一般饮食原则，不用于个体诊断 |

规则阈值、算力安排、页面、分工、实验目标均为项目设计，不是以上资料承诺的准确率。

2026-10-10：[vision-demos 固定版本](https://github.com/jeremyipark/vision-demos/tree/8e1467ec39ac5b6b992ce748294664b87382756c)，查看各动作的 reps、ROM、校准、姿态网关和相似度实现，评估结果见 VISION_DEMOS_REVIEW。
