import io
import json
import logging
import os
import re
import shutil
import zipfile

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView

from .models import Skill

logger = logging.getLogger(__name__)

# 技能文件存储根目录
SKILLS_STORAGE = os.path.join(settings.BASE_DIR, "skills_storage")


def _parse_yaml_frontmatter(text: str) -> dict:
    """解析 Markdown 的 YAML frontmatter（简易实现）"""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    result = {}
    for line in m.group(1).split("\n"):
        line = line.strip()
        if ":" in line and not line.startswith("#"):
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            # 处理列表: [a, b, c]
            if val.startswith("[") and val.endswith("]"):
                val = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",")]
            result[key] = val
    return result


def _extract_body(text: str) -> str:
    """提取 frontmatter 之后的正文"""
    m = re.match(r"^---\s*\n.*?\n---\s*\n", text, re.DOTALL)
    if m:
        return text[m.end():]
    return text


class SkillListView(ListView):
    model = Skill
    template_name = "skills/skill_list.html"
    context_object_name = "skills"


class SkillDetailView(DetailView):
    model = Skill
    template_name = "skills/skill_detail.html"
    context_object_name = "skill"


class SkillCreateView(CreateView):
    model = Skill
    template_name = "skills/skill_form.html"
    fields = ["name", "description", "category", "instruction", "is_active"]

    def get_success_url(self):
        return reverse_lazy("skills:detail", kwargs={"pk": self.object.pk})


class SkillUpdateView(UpdateView):
    model = Skill
    template_name = "skills/skill_form.html"
    fields = ["name", "description", "category", "instruction", "is_active"]

    def get_success_url(self):
        return reverse_lazy("skills:detail", kwargs={"pk": self.object.pk})


class SkillDeleteView(DeleteView):
    model = Skill
    template_name = "skills/skill_confirm_delete.html"
    success_url = reverse_lazy("skills:list")


# ------------------------------------------------------------------
# 批量导入
# ------------------------------------------------------------------

def skill_import(request):
    """
    上传技能 zip 包，批量导入。

    zip 结构规范（Agent Skills 标准格式）：
        skills.zip
          ├── skill-name/
          │   ├── SKILL.md          ← 主技能文件（必选，含 YAML frontmatter）
          │   ├── script.py         ← 可执行脚本（可选）
          │   └── ...
          └── ...

    SKILL.md frontmatter 支持: name, description, allowed_tools, tags
    """
    if request.method != "POST":
        return redirect("skills:list")

    zip_file = request.FILES.get("zip_file")
    if not zip_file:
        messages.error(request, "请选择要上传的 zip 文件")
        return redirect("skills:list")

    if not zip_file.name.endswith(".zip"):
        messages.error(request, "仅支持 .zip 格式的压缩包")
        return redirect("skills:list")

    created = []
    updated = []
    errors = []

    # 确保存储目录存在
    os.makedirs(SKILLS_STORAGE, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_file, "r") as zf:
            # 收集所有 skill 目录（保留子目录结构）
            skill_dirs: dict[str, dict[str, str]] = {}
            for entry in zf.namelist():
                if entry.endswith("/") or entry.startswith(".") or entry.startswith("__"):
                    continue
                parts = entry.split("/")
                if len(parts) < 2:
                    continue
                dir_name = parts[0]
                rel_path = "/".join(parts[1:])
                if dir_name not in skill_dirs:
                    skill_dirs[dir_name] = {}
                skill_dirs[dir_name][rel_path] = entry

            if not skill_dirs:
                messages.error(request, "zip 中没有找到有效的 skill 目录")
                return redirect("skills:list")

            for dir_name, files in skill_dirs.items():
                try:
                    # 查找 SKILL.md
                    skill_md_path = None
                    for fpath in files:
                        if fpath.lower().endswith("skill.md"):
                            skill_md_path = fpath
                            break
                    if not skill_md_path:
                        errors.append(f"「{dir_name}」缺少 SKILL.md，已跳过")
                        continue

                    # 读取并解析 SKILL.md
                    raw = zf.read(files[skill_md_path]).decode("utf-8")
                    fm = _parse_yaml_frontmatter(raw)
                    body = _extract_body(raw)

                    name = fm.get("name", dir_name)
                    description = fm.get("description", "")
                    tools_raw = fm.get("allowed_tools", [])
                    if isinstance(tools_raw, list):
                        allowed_tools = ", ".join(tools_raw)
                    else:
                        allowed_tools = str(tools_raw) if tools_raw else ""

                    # 解压完整目录到 skills_storage/
                    extract_dir = os.path.join(SKILLS_STORAGE, dir_name)
                    if os.path.exists(extract_dir):
                        shutil.rmtree(extract_dir)
                    os.makedirs(extract_dir)
                    for fpath, zpath in files.items():
                        target = os.path.join(extract_dir, fpath.replace("/", os.sep))
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        with zf.open(zpath) as src, open(target, "wb") as dst:
                            dst.write(src.read())

                    # 创建或更新
                    skill, is_new = Skill.objects.update_or_create(
                        name=name,
                        defaults={
                            "description": description,
                            "category": "general",
                            "instruction": body,
                            "script_dir": extract_dir,
                            "allowed_tools": allowed_tools,
                            "is_active": True,
                        },
                    )
                    (created if is_new else updated).append(name)

                except Exception as e:
                    errors.append(f"「{dir_name}」处理失败: {e}")
                    logger.exception("Skill import error: %s", dir_name)

    except zipfile.BadZipFile:
        messages.error(request, "文件不是有效的 zip 压缩包")
        return redirect("skills:list")
    except Exception as e:
        messages.error(request, f"导入失败: {e}")
        logger.exception("Skill import failed")
        return redirect("skills:list")

    # 汇总结果
    msg_parts = []
    if created:
        msg_parts.append(f"新增 {len(created)} 个技能: {', '.join(created)}")
    if updated:
        msg_parts.append(f"更新 {len(updated)} 个技能: {', '.join(updated)}")
    if errors:
        msg_parts.append(f"失败 {len(errors)}: {'; '.join(errors)}")
    if not msg_parts:
        msg_parts.append("未找到可导入的技能")

    messages.success(request, " · ".join(msg_parts) if created or updated else " · ".join(msg_parts))
    return redirect("skills:list")
