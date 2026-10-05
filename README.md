# FoldBot ROS 2 — 真机部署工程

> FoldBot behavior-tree clothes-folding robot, sim-to-real.
> 把仿真里验证过的折叠逻辑搬到真机机械臂上。

## 进展

看 `dashboard/index.html`（直接浏览器打开），有行为树可视化、里程碑和每日日志。

## 里程碑

- **M0** (Day 1): 接口包 + BT 空主干 + mock 感知，主树跑通 ✅
- **M1**: fold.js 数学移植到 Python + 单元测试
- **M2**: planner.js 移植（planFolds / planPantsFolds / classifyOwner）
- **M3**: PickFromBasket 子树细化
- **M4**: PerceiveAndPlan 子树细化
- **M5**: FoldStep / SortToBin 子树细化
- **Board**: 叠衣板（75×72cm，三列25cm，中间36+36）— 机械臂抓板边翻折

## 叠衣板 / Folding Board

75×72cm 板，左/右/中三列各25cm宽，中间列分上下两块36cm。
机械臂**抓板边**翻折（v1.2，替代从下推）：抓边 → 上翻 → 停顿 → 放回 → 松开。
`planning/board.py` 有 `BoardFoldSimulator`（顶点级折叠验证，和可视化同数学）。
短袖：翻左 → 翻右 → 翻底；长袖先收袖；裤子先对折再上板。

## 结构

```
foldbot-ros2/
├── bt/              # 行为树 (py_trees, 真机用 BehaviorTree.CPP)
├── perception/      # 感知 (M0 用 mock, 真机换 learned 模型)
├── planning/        # 折叠规划 (从 planner.js/fold.js 移植)
├── execution/       # 执行原语 (真机对接 MoveIt2)
├── msgs/            # 接口定义 (ROS 2 .msg/.srv, 现在用 Python dataclass)
├── tests/           # 单元测试
├── dashboard/       # HTML 进展看板
└── docs/
```

## 跑 M0

```bash
pip install py_trees
python3 -m tests.test_m0
python3 bt/main_tree.py  # 跑一遍主树，看节点状态流转
```

## 设计文档

`docs/` 下有完整的 ROS 2 行为树设计文档（PDF）。
