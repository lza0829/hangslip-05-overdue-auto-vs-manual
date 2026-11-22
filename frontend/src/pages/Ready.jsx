import { useEffect, useState } from "react";
import { api } from "../api";

export default function Ready() {
  const [rows, setRows] = useState([]);
  const [codes, setCodes] = useState({});
  const [msg, setMsg] = useState("");
  const [today, setToday] = useState("");

  async function load() {
    setRows(await api.挂牌列表("?status=" + encodeURIComponent("待取")));
  }

  useEffect(() => {
    load().catch((e) => setMsg(e.message));
    api
      .日闸今日()
      .then((p) => setToday(p.day))
      .catch(() => {});
  }, []);

  async function pick(ticket_no) {
    setMsg("");
    try {
      await api.取衣(ticket_no, {
        pickup_code: codes[ticket_no] || "",
        operator: "柜员",
      });
      setMsg(`${ticket_no} 已取衣核销`);
      setCodes({ ...codes, [ticket_no]: "" });
      await load();
    } catch (e) {
      setMsg(e.message);
      await load().catch(() => {});
    }
  }

  const overdue = (r) => r.due_date && today && r.due_date < today;

  return (
    <section className="panel">
      <h3>待取核销</h3>
      <p className={`msg ${msg.includes("已取") ? "ok" : ""}`}>{msg}</p>
      <p className="hint">
        待取页只展示现行「待取」票。逾承诺日的票在此仍可按暗码取衣，或等到点扫描把它改入超期隔离；两者争用同一张票，不会同时成立。
      </p>
      <table>
        <thead>
          <tr>
            <th>票号</th>
            <th>顾客</th>
            <th>承诺日</th>
            <th>暗码</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.ticket_no}>
              <td>{r.ticket_no}</td>
              <td>{r.customer_name}</td>
              <td>
                {r.due_date || "—"}{" "}
                {overdue(r) && <span className="badge 超期隔离">逾承诺日</span>}
              </td>
              <td>
                <input
                  placeholder="输入暗码"
                  value={codes[r.ticket_no] || ""}
                  onChange={(e) =>
                    setCodes({ ...codes, [r.ticket_no]: e.target.value })
                  }
                />
              </td>
              <td>
                <button type="button" onClick={() => pick(r.ticket_no)}>
                  核销取衣
                </button>
              </td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={5}>当前没有待取票。</td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}
