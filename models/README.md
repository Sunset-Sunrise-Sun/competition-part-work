# 模型资产

不提交模型权重。姿态模型用 `npm run prepare:models` 下载到 `frontend/public/models`；脚本会保存来源、SHA-256 和准备时间。

可选中文 LLM：先查看官方模型卡及许可，再使用 llama.cpp 在同机回环地址启动服务。不要把生产健康信息发送给公共模型接口。

SMPL / SMPL-X 官方权重在实验室机器的 GVHMR / GMR 目录中，例如：

- `gvhmr/inputs/checkpoints/body_models/smpl/SMPL_*.pkl`
- `gvhmr/inputs/checkpoints/body_models/smplx/SMPLX_*.npz`
- `gmr/assets/body_models/smplx/SMPLX_*.npz`

网页使用从 `SMPLX_NEUTRAL.npz` 导出的 55 关节模板与 10 维 shape 基（`frontend/src/smplx_official.json`），按 GVHMR `J = J_template + β·J_shapedirs` 和 GMR `height ≈ 1.66 + 0.1·β0` 做体型。完整 pkl/npz 不提交仓库。

权重、缓存、WASM 不属于当前仓库的原创代码许可证。详见 `docs/DEPENDENCIES.md`。
