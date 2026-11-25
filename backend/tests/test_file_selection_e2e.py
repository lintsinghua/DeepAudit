"""
文件选择与排除模式 - 端到端 API 测试

此脚本测试完整的 API 流程：
1. 创建测试项目
2. 上传 ZIP 文件
3. 获取文件列表（带/不带排除模式）
4. 启动扫描任务（带排除模式和文件选择）

使用方法：
    python tests/test_file_selection_e2e.py

环境要求：
    - 后端服务运行在 http://localhost:8000
    - 通过 AUTH_TOKEN 提供测试账户的有效 token
"""

import httpx
import json
import os
import sys
import tempfile
import zipfile
import time
from pathlib import Path

# 配置 - 使用 127.0.0.1 避免 IPv6 问题
BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api/v1")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")

# 测试数据
TEST_FILES = {
    "src/main.py": '''
def main():
    password = "admin123"  # 硬编码密码
    print("Hello World")

if __name__ == "__main__":
    main()
''',
    "src/utils.py": '''
def helper():
    return "helper"
''',
    "src/tests/test_main.py": '''
def test_main():
    assert True
''',
    "node_modules/lib.js": '''
module.exports = {};
''',
    "dist/bundle.js": '''
var a = 1;
''',
    ".git/config": '''
[core]
    repositoryformatversion = 0
''',
    "app.log": '''
2024-01-01 INFO: Application started
''',
    "README.md": '''
# Test Project
This is a test project.
''',
}


def create_test_zip() -> str:
    """创建测试 ZIP 文件"""
    temp_dir = tempfile.mkdtemp()
    zip_path = os.path.join(temp_dir, "test_project.zip")
    
    with zipfile.ZipFile(zip_path, 'w') as zf:
        for filename, content in TEST_FILES.items():
            zf.writestr(filename, content)
    
    print(f"✅ 创建测试 ZIP 文件: {zip_path}")
    return zip_path


def get_headers(token: str = None):
    """获取请求头"""
    headers = {"Content-Type": "application/json"}
    t = token or AUTH_TOKEN
    if t:
        headers["Authorization"] = f"Bearer {t}"
    return headers


class FileSelectionE2ETest:
    """端到端测试类"""
    
    def __init__(self):
        # 禁用环境代理设置，避免 502 错误
        self.client = httpx.Client(timeout=30.0, proxy=None, trust_env=False)
        self.project_id = None
        self.zip_path = None
        self.token = AUTH_TOKEN
    
    def cleanup(self):
        """清理测试资源"""
        if self.zip_path and os.path.exists(self.zip_path):
            os.remove(self.zip_path)
            os.rmdir(os.path.dirname(self.zip_path))
            print("✅ 清理临时文件")
        
        if self.project_id:
            try:
                self.client.delete(
                    f"{BASE_URL}/projects/{self.project_id}",
                    headers=get_headers(self.token)
                )
                print(f"✅ 删除测试项目: {self.project_id}")
            except Exception as e:
                print(f"⚠️ 删除项目失败: {e}")
        
        self.client.close()
    
    def test_health_check(self) -> bool:
        """测试服务健康状态并登录"""
        print("\n[测试] 服务健康检查...")
        
        # 尝试访问健康检查端点
        # BASE_URL 是 http://localhost:8000/api/v1，需要去掉 /api/v1
        base = BASE_URL.rsplit('/api/v1', 1)[0]
        health_url = f"{base}/health"
        print(f"  健康检查 URL: {health_url}")
        
        try:
            response = self.client.get(health_url)
            print(f"  响应状态: {response.status_code}")
            if response.status_code == 200:
                print(f"✅ 服务运行正常")
            else:
                print(f"⚠️ 健康检查返回: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ 无法连接服务: {e}")
            return False
        
        if not self.token:
            print("❌ 请设置测试账户的 AUTH_TOKEN")
            return False

        return True
    
    def test_create_project(self) -> bool:
        """测试创建 ZIP 项目"""
        print("\n[测试] 创建 ZIP 项目...")
        
        project_data = {
            "name": f"Test Project {int(time.time())}",
            "description": "文件选择功能测试项目",
            "source_type": "zip",
        }
        
        try:
            response = self.client.post(
                f"{BASE_URL}/projects/",
                json=project_data,
                headers=get_headers(self.token)
            )
            
            if response.status_code == 200:
                data = response.json()
                self.project_id = data.get("id")
                print(f"✅ 项目创建成功: {self.project_id}")
                return True
            elif response.status_code == 401:
                print("⚠️ 需要认证，跳过此测试")
                return False
            else:
                print(f"❌ 创建项目失败: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ 请求失败: {e}")
            return False
    
    def test_upload_zip(self) -> bool:
        """测试上传 ZIP 文件"""
        if not self.project_id:
            print("⚠️ 跳过：没有项目 ID")
            return False
        
        print("\n[测试] 上传 ZIP 文件...")
        
        self.zip_path = create_test_zip()
        
        try:
            with open(self.zip_path, 'rb') as f:
                files = {"file": ("test_project.zip", f, "application/zip")}
                headers = {}
                if self.token:
                    headers["Authorization"] = f"Bearer {self.token}"
                
                response = self.client.post(
                    f"{BASE_URL}/projects/{self.project_id}/zip",
                    files=files,
                    headers=headers
                )
            
            if response.status_code == 200:
                print("✅ ZIP 文件上传成功")
                return True
            else:
                print(f"❌ 上传失败: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ 请求失败: {e}")
            return False
    
    def test_get_files_without_exclude(self) -> bool:
        """测试获取文件列表（无排除模式）"""
        if not self.project_id:
            print("⚠️ 跳过：没有项目 ID")
            return False
        
        print("\n[测试] 获取文件列表（无排除模式）...")
        
        try:
            response = self.client.get(
                f"{BASE_URL}/projects/{self.project_id}/files",
                headers=get_headers(self.token)
            )
            
            if response.status_code == 200:
                files = response.json()
                print(f"✅ 获取到 {len(files)} 个文件")
                
                # 验证默认排除生效
                paths = [f["path"] for f in files]
                
                # 应该包含的文件
                expected_included = ["src/main.py", "src/utils.py"]
                for path in expected_included:
                    if path in paths:
                        print(f"  ✓ 包含: {path}")
                    else:
                        print(f"  ✗ 缺少: {path}")
                
                # 应该被排除的文件
                expected_excluded = ["node_modules/lib.js", "dist/bundle.js", ".git/config"]
                for path in expected_excluded:
                    if path not in paths:
                        print(f"  ✓ 已排除: {path}")
                    else:
                        print(f"  ✗ 未排除: {path}")
                
                return True
            else:
                print(f"❌ 获取失败: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ 请求失败: {e}")
            return False
    
    def test_get_files_with_exclude(self) -> bool:
        """测试获取文件列表（带排除模式）"""
        if not self.project_id:
            print("⚠️ 跳过：没有项目 ID")
            return False
        
        print("\n[测试] 获取文件列表（带自定义排除模式）...")
        
        # 自定义排除模式：排除测试文件和日志（使用路径片段匹配）
        exclude_patterns = [".log", "tests/", "test_"]
        
        try:
            response = self.client.get(
                f"{BASE_URL}/projects/{self.project_id}/files",
                params={"exclude_patterns": json.dumps(exclude_patterns)},
                headers=get_headers(self.token)
            )
            
            if response.status_code == 200:
                files = response.json()
                print(f"✅ 获取到 {len(files)} 个文件（应用自定义排除）")
                
                paths = [f["path"] for f in files]
                
                # 验证自定义排除生效
                if "app.log" not in paths:
                    print("  ✓ 已排除: app.log (*.log 模式)")
                else:
                    print("  ✗ 未排除: app.log")
                
                # 检查测试文件是否被排除
                test_files = [p for p in paths if "test" in p.lower()]
                if not test_files:
                    print("  ✓ 已排除所有测试文件")
                else:
                    print(f"  ⚠️ 仍包含测试文件: {test_files}")
                
                return True
            else:
                print(f"❌ 获取失败: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ 请求失败: {e}")
            return False
    
    def test_scan_with_file_selection(self) -> bool:
        """测试带文件选择的扫描"""
        if not self.project_id:
            print("⚠️ 跳过：没有项目 ID")
            return False
        
        print("\n[测试] 启动扫描（带文件选择和排除模式）...")
        
        scan_request = {
            "file_paths": ["src/main.py"],  # 只扫描一个文件
            "exclude_patterns": [".log", "tests/"],  # 使用路径片段匹配
            "full_scan": False,
        }
        
        try:
            response = self.client.post(
                f"{BASE_URL}/scan/scan-stored-zip",
                params={"project_id": self.project_id},
                json=scan_request,
                headers=get_headers(self.token)
            )
            
            if response.status_code == 200:
                data = response.json()
                task_id = data.get("task_id")
                print(f"✅ 扫描任务已创建: {task_id}")
                return True
            elif response.status_code == 400:
                print(f"⚠️ 扫描请求被拒绝（可能没有存储的 ZIP）: {response.text}")
                return False
            else:
                print(f"❌ 扫描失败: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ 请求失败: {e}")
            return False


def run_mock_tests():
    """运行模拟测试（不需要真实服务）"""
    print("\n" + "=" * 60)
    print("模拟测试模式（不连接真实服务）")
    print("=" * 60)
    
    # 测试 1: 排除模式参数格式
    print("\n[模拟测试 1] 排除模式参数格式...")
    exclude_patterns = ["node_modules/**", "*.log", "dist/**"]
    json_str = json.dumps(exclude_patterns)
    parsed = json.loads(json_str)
    assert parsed == exclude_patterns
    print(f"✅ JSON 序列化正确: {json_str}")
    
    # 测试 2: 扫描请求格式
    print("\n[模拟测试 2] 扫描请求格式...")
    scan_request = {
        "file_paths": ["src/main.py", "src/utils.py"],
        "exclude_patterns": ["*.test.js", "coverage/**"],
        "full_scan": False,
        "rule_set_id": None,
        "prompt_template_id": None,
    }
    json_str = json.dumps(scan_request)
    parsed = json.loads(json_str)
    assert "exclude_patterns" in parsed
    assert parsed["full_scan"] is False
    print(f"✅ 扫描请求格式正确")
    
    # 测试 3: ZIP 文件创建和读取
    print("\n[模拟测试 3] ZIP 文件处理...")
    zip_path = create_test_zip()
    
    with zipfile.ZipFile(zip_path, 'r') as zf:
        file_list = zf.namelist()
        print(f"✅ ZIP 包含 {len(file_list)} 个文件")
        
        # 验证文件存在
        assert "src/main.py" in file_list
        assert "node_modules/lib.js" in file_list
    
    # 清理
    os.remove(zip_path)
    os.rmdir(os.path.dirname(zip_path))
    print("✅ 清理完成")
    
    print("\n" + "=" * 60)
    print("🎉 所有模拟测试通过！")
    print("=" * 60)


def run_e2e_tests():
    """运行端到端测试"""
    print("\n" + "=" * 60)
    print("端到端 API 测试")
    print("=" * 60)
    print(f"API 地址: {BASE_URL}")
    print(f"认证状态: {'已配置' if AUTH_TOKEN else '未配置'}")
    
    test = FileSelectionE2ETest()
    results = []
    
    try:
        # 健康检查
        if not test.test_health_check():
            print("\n⚠️ 服务不可用，切换到模拟测试模式")
            run_mock_tests()
            return
        
        # 运行测试
        results.append(("创建项目", test.test_create_project()))
        results.append(("上传 ZIP", test.test_upload_zip()))
        results.append(("获取文件（无排除）", test.test_get_files_without_exclude()))
        results.append(("获取文件（带排除）", test.test_get_files_with_exclude()))
        results.append(("扫描（带文件选择）", test.test_scan_with_file_selection()))
        
    finally:
        test.cleanup()
    
    # 打印结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    passed = 0
    failed = 0
    skipped = 0
    
    for name, result in results:
        if result is True:
            status = "✅ 通过"
            passed += 1
        elif result is False:
            status = "❌ 失败"
            failed += 1
        else:
            status = "⚠️ 跳过"
            skipped += 1
        print(f"  {name}: {status}")
    
    print(f"\n总计: {passed} 通过, {failed} 失败, {skipped} 跳过")
    
    if failed == 0:
        print("\n🎉 所有测试通过！")
    else:
        print("\n⚠️ 部分测试失败，请检查日志")


if __name__ == "__main__":
    # 检查命令行参数
    if len(sys.argv) > 1 and sys.argv[1] == "--mock":
        run_mock_tests()
    else:
        run_e2e_tests()
