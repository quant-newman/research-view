// 复盘页分页边界(施工令 六.15):0/1/8/9 篇 + 数据缩减页码越界自动回合法页。
// 纯函数直测(node --test),组件消费同一模块不再自算。
import test from "node:test";
import assert from "node:assert/strict";
import { PER_PAGE, totalPages, clampPage, pageSlice } from "../src/reflectionsPaging.js";

test("每页 8 篇", () => assert.equal(PER_PAGE, 8));

test("0 篇:1 页,空切片,页码合法", () => {
  assert.equal(totalPages(0), 1);
  assert.equal(clampPage(1, 0), 1);
  assert.deepEqual(pageSlice(1, 0), { page: 1, start: 0, end: 0 });
});

test("1 篇:1 页,切出唯一一篇", () => {
  assert.equal(totalPages(1), 1);
  assert.deepEqual(pageSlice(1, 1), { page: 1, start: 0, end: 1 });
});

test("8 篇:恰好 1 页,不多出空页", () => {
  assert.equal(totalPages(8), 1);
  assert.deepEqual(pageSlice(1, 8), { page: 1, start: 0, end: 8 });
});

test("9 篇:2 页,第 2 页只有第 9 篇(翻页后内容仍可访问,非截断)", () => {
  assert.equal(totalPages(9), 2);
  assert.deepEqual(pageSlice(1, 9), { page: 1, start: 0, end: 8 });
  assert.deepEqual(pageSlice(2, 9), { page: 2, start: 8, end: 9 });
});

test("数据缩减页码越界:第 3 页看着 20 篇,缩到 9 篇自动回第 2 页;缩到 0 回第 1 页", () => {
  assert.equal(clampPage(3, 20), 3);
  assert.equal(clampPage(3, 9), 2);
  assert.equal(clampPage(3, 0), 1);
  assert.deepEqual(pageSlice(3, 9), { page: 2, start: 8, end: 9 });
});

test("非法页码:0/负数/NaN 一律回第 1 页", () => {
  assert.equal(clampPage(0, 9), 1);
  assert.equal(clampPage(-5, 9), 1);
  assert.equal(clampPage(NaN, 9), 1);
});
