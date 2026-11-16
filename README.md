# Parkfolio 公园书店湖仓

Parkfolio 为公园书店提供离线可运行的事件湖仓。系统分别记录阅读空间、访客会话、图书阅读、读书会参与、图书销售与餐饮交易，再形成可追溯的月度报表。仓库里的演示数据均为本地合成数据，不含新闻报道中店铺的真实经营数据。

## 启动与验收

依赖版本固定在 requirements.txt。在已准备依赖的环境中，运行 python -m unittest discover -s tests -v 执行业务测试，运行 python -m compileall -q parkfolio 检查源码，运行 python -m parkfolio.demo 检验从乱序事件到冻结发布的完整流程。API 可通过 uvicorn parkfolio.api:app --host 127.0.0.1 --port 8000 启动。数据库路径可用 PARKFOLIO_DB 环境变量指定，缺省为当前目录的 parkfolio.sqlite3。

命令行入口为 python -m parkfolio --db data.sqlite3，子命令有 overview、report YYYY-MM、quality YYYY-MM、preview YYYY-MM、publish 名称 月份 指纹、load 批次号 事件文件，以及 retry 事件编号。

## 事件与指标

先登记门店、带生效区间的阅读空间、馆藏、活动及各来源通道。访客进入有效的阅读区或混合区后可形成阅读事件；活动签到必须对应同一访客、时段和活动空间，并受场地容量限制。订单按图书、餐食和饮品分类，退款关联原单且总额不能超过原单。缺少会话、馆藏或原单的原始事件进入隔离区，补齐引用后可重试。同一来源编号与内容重复送达不会重复记账；编号相同而内容不同则拒绝。

月报分别显示访客、阅读分钟、主题、活动参与及各类净收入，并保留原始事件编号作为血缘。质量视图指出待解决输入与业务一致性问题。发布时提供预览指纹，系统核对当前质量和内容后冻结快照；之后的新事件只改变当前报表，不覆盖既有发布。
