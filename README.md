# Survey Mentor

让 AI 读完一篇综述论文，自动成为该领域的导师（Survey Mentor）。用户之后可以随时提问，获得领域指导、概念解释、方法比较和研究方向判断。

## 技能做什么

1. 按论文标题 / arXiv ID 从 arXiv 下载综述的 PDF 和 LaTeX 源码
2. 读 LaTeX 确认是综述（非综述不做 Mentor，建议换综述）
3. 完整通读 LaTeX，建立领域知识体系（领域地图、概念网络、方法地图、发展脉络、问题地图、判断框架）
4. 输出 Mentor Profile 并保存到论文目录
5. 以该领域导师的身份与用户持续对话

## 目录结构

```
survey-mentor/
├── SKILL.md                        # 技能主文件（工作流程）
├── references/
│   └── mentor-protocol.md          # 导师行为规范（阅读、领域大脑、对话、表达、知识依据）
├── scripts/
│   └── fetch_arxiv.py              # 从 arXiv 下载 PDF 
├── README.md
└── LICENSE
```

## 安装

把本仓库复制（或软链接）到 ZCode 的技能目录：

```bash
mkdir -p ~/.agents/skills
cp -r . ~/.agents/skills/survey-mentor
```

## 使用示例

> 帮我下载综述《A Survey of Large Language Models》，我要问它几个问题

> 下载 arXiv 2312.09328 这篇综述，当我的领域导师
