模块一，测试文件放在backend文件夹下，直接运行test.py即可



模块二 AI测试脚本

````
## 运行方式

### 前置条件

- Python 3.10+，且 `backend` 的依赖已安装（FastAPI、pydantic 等）。
- `pytest` 未安装时先执行：

```powershell
pip install pytest
```

### 一键运行全部用例

在**项目根目录**执行：

```powershell
python -m pytest custom_tests -q --disable-warnings
```

运行结束输出 `40 passed` 即全部通过；退出码 0 表示成功。
````
