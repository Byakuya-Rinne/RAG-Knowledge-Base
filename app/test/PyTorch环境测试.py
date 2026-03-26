



import torch
print("XPU available:", torch.xpu.is_available())  # 若 False 则不支持
print("XPU device count:", torch.xpu.device_count())
print("PyTorch 版本:", torch.__version__)
print("是否支持 CUDA:", torch.cuda.is_available())
print("CUDA 版本 (如果支持):", torch.version.cuda if torch.cuda.is_available() else "N/A")
if torch.cuda.is_available():
    print("GPU 数量:", torch.cuda.device_count())
    print("当前 GPU 名称:", torch.cuda.get_device_name(0))
else:
    print("未检测到 CUDA/ROCm 设备")
# 尝试在 GPU 上创建张量（根据实际设备选择 'cuda' 或 'xpu'）
if torch.cuda.is_available():
    device = torch.device('cuda')
elif hasattr(torch, 'xpu') and torch.xpu.is_available():
    device = torch.device('xpu')
else:
    device = torch.device('cpu')

x = torch.randn(3, 3).to(device)
y = torch.randn(3, 3).to(device)
z = x @ y
print("张量运算成功，结果形状:", z.shape)
print("结果所在设备:", z.device)










