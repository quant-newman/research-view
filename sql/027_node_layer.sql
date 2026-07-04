-- 参照层 v2(机器人链,DECISIONS #31):节点加 layer 分层(Brain/Body-*/Integrator/Enabler),
-- 展示分组用,nullable 不影响任何消费方;非机器人链节点为 NULL。
ALTER TABLE node ADD COLUMN IF NOT EXISTS layer text;
