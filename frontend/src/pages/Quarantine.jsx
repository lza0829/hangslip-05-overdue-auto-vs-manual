import { useEffect, useState } from "react";
import { api } from "../api";

function ScanPanel({ onChanged }) {
  const [pending, setPending] = useState([]);
  const [scan, setScan] = useState(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const [p, list] = await Promise.all([api.超期待扫(), api.扫描列表()]);
    setPending(p);
    setScan(list[0] || null);
  }

  useEffect(() => {
    load().catch((e) => setMsg(e.message));
  }, []);

  async function run() {
    setBusy(true);
    setMsg("");
    try {
      const row = await api.运行扫描({ operator: "店长", note: "到点扫描" });
      setMsg(
        `扫描 #${row.id} 完成：核对 ${row.scanned} 张，隔离 ${row.quarantined} 张，跳过 ${row.skipped} 张`
      );
      await load();
      onChanged?.();
    } catch (e) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h3>到点扫描（超期进隔离唯一入口）</h3>
      <p className={`msg ${msg.startsWith("扫描") ? "ok" : ""}`}>{msg}</p>
      <p className="hint">
        逾承诺日仍待取的票由本扫描统一改入超期隔离并写出流水；扫描落定后待取页不再展示、总览超期数归零，在途水位与重放口径保持一致。
      </p>
      <div className="row">
        <div className="metric">
          <b>{pending.length}</b>
          <span>待扫超期票</span>
        </div>
        <div className="metric">
          <b>{scan?.quarantined ?? "—"}</b>
          <span>最近一次落隔离</span>
        </div>
        <button type="button" onClick={run} disabled={busy}>
          {busy ? "扫描中…" : "运行超期扫描"}
        </button>
      </div>
      <table>
        <thead>
          <tr>
            <th>票号</th>
            <th>门店</th>
            <th>顾客</th>
            <th>承诺日</th>
            <th>现行</th>
          </tr>
        </thead>
        <tbody>
          {pending.map((r) => (
            <tr key={r.ticket_no}>
              <td>{r.ticket_no}</td>
              <td>{r.store_code}</td>
              <td>{r.customer_name}</td>
              <td>{r.due_date}</td>
              <td>
                <span className={`badge ${r.status}`}>{r.status}</span>
              </td>
            </tr>
          ))}
          {!pending.length && (
            <tr>
              <td colSpan={5}>没有逾承诺日仍待取的票。</td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}

function ScanHistory({ tick }) {
  const [rows, setRows] = useState([]);
  const [open, setOpen] = useState(null);
  const [msg, setMsg] = useState("");

  async function load() {
    setRows(await api.扫描列表());
  }

  useEffect(() => {
    load().catch((e) => setMsg(e.message));
  }, [tick]);

  async function toggle(id) {
    if (open === id) {
      setOpen(null);
      return;
    }
    try {
      setOpen(await api.扫描详情(id));
    } catch (e) {
      setMsg(e.message);
    }
  }

  return (
    <section className="panel">
      <h3>扫描记录</h3>
      <p className="msg">{msg}</p>
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>日期</th>
            <th>操作人</th>
            <th>核对</th>
            <th>隔离</th>
            <th>跳过</th>
            <th>水位变化</th>
            <th>待取变化</th>
            <th>明细</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.id}</td>
              <td>{r.day}</td>
              <td>{r.operator}</td>
              <td>{r.scanned}</td>
              <td>{r.quarantined}</td>
              <td>{r.skipped}</td>
              <td>
                {r.in_flight_before} → {r.in_flight_after}
              </td>
              <td>
                {r.ready_before} → {r.ready_after}
              </td>
              <td>
                <button type="button" className="ghost" onClick={() => toggle(r.id)}>
                  {open?.id === r.id ? "收起" : "查看"}
                </button>
              </td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={9}>尚无扫描记录。</td>
            </tr>
          )}
        </tbody>
      </table>
      {open && (
        <table>
          <thead>
            <tr>
              <th>票号</th>
              <th>判定</th>
              <th>扫描时状态</th>
              <th>承诺日</th>
              <th>备注</th>
            </tr>
          </thead>
          <tbody>
            {(open.items || []).map((i) => (
              <tr key={i.id}>
                <td>{i.ticket_no}</td>
                <td>{i.decision}</td>
                <td>{i.observed_status}</td>
                <td>{i.due_date}</td>
                <td>{i.note || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function ReplayCheck({ tick }) {
  const [snap, setSnap] = useState(null);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api
      .扫描核对()
      .then(setSnap)
      .catch((e) => setMsg(e.message));
  }, [tick]);

  return (
    <section className="panel">
      <h3>重放核对</h3>
      <p className={`msg ${snap?.一致 ? "ok" : ""}`}>
        {msg || (snap && (snap.一致 ? "隔离流水与取衣记录可重放出当前票态。" : "重放结果与现行票态不一致。"))}
      </p>
      {snap && (
        <>
          <table>
            <thead>
              <tr>
                <th>口径</th>
                <th>重放</th>
                <th>现行</th>
                <th>一致</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>待取数</td>
                <td>{snap.重放待取}</td>
                <td>{snap.现行待取}</td>
                <td>{snap.待取一致 ? "是" : "否"}</td>
              </tr>
              <tr>
                <td>在途水位</td>
                <td>{snap.重放在途}</td>
                <td>{snap.现行水位}</td>
                <td>{snap.水位一致 ? "是" : "否"}</td>
              </tr>
              <tr>
                <td>扫描落隔离数</td>
                <td colSpan={3}>{snap.扫描落隔离数}</td>
              </tr>
            </tbody>
          </table>
          {!!snap.票态不一致?.length && (
            <table>
              <thead>
                <tr>
                  <th>票号</th>
                  <th>现行</th>
                  <th>重放</th>
                </tr>
              </thead>
              <tbody>
                {snap.票态不一致.map((m) => (
                  <tr key={m.ticket_no}>
                    <td>{m.ticket_no}</td>
                    <td>{m.现行}</td>
                    <td>{m.重放}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}

export default function Quarantine() {
  const [ready, setReady] = useState([]);
  const [logs, setLogs] = useState([]);
  const [msg, setMsg] = useState("");
  const [tick, setTick] = useState(0);

  async function load() {
    const [a, b] = await Promise.all([
      api.挂牌列表("?status=" + encodeURIComponent("待取")),
      api.隔离列表(),
    ]);
    setReady(a);
    setLogs(b);
  }

  useEffect(() => {
    load().catch((e) => setMsg(e.message));
  }, [tick]);

  async function lost(ticket_no) {
    setMsg("");
    try {
      await api.隔离(ticket_no, {
        kind: "丢失隔离",
        reason: "店内申报丢失",
        operator: "店长",
      });
      setMsg(`${ticket_no} → 丢失隔离`);
      setTick((t) => t + 1);
    } catch (e) {
      setMsg(e.message);
    }
  }

  return (
    <>
      <ScanPanel onChanged={() => setTick((t) => t + 1)} />
      <ScanHistory tick={tick} />
      <ReplayCheck tick={tick} />
      <section className="panel">
        <h3>待取票人工报失</h3>
        <p className="msg">{msg}</p>
        <p className="hint">
          超期进隔离不在此点选：逾承诺日的待取票由上方到点扫描统一落定；本表只处理店内申报丢失。
        </p>
        <table>
          <thead>
            <tr>
              <th>票号</th>
              <th>承诺日</th>
              <th>顾客</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {ready.map((r) => (
              <tr key={r.ticket_no}>
                <td>{r.ticket_no}</td>
                <td>{r.due_date}</td>
                <td>{r.customer_name}</td>
                <td>
                  <button type="button" className="ghost" onClick={() => lost(r.ticket_no)}>
                    丢失隔离
                  </button>
                </td>
              </tr>
            ))}
            {!ready.length && (
              <tr>
                <td colSpan={4}>当前没有待取票。</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
      <section className="panel">
        <h3>隔离流水</h3>
        <table>
          <thead>
            <tr>
              <th>票号</th>
              <th>种类</th>
              <th>来源</th>
              <th>扫描</th>
              <th>原状态</th>
              <th>原因</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((r) => (
              <tr key={r.id}>
                <td>{r.ticket_no}</td>
                <td>
                  <span className={`badge ${r.kind}`}>{r.kind}</span>
                </td>
                <td>{r.source}</td>
                <td>{r.scan_id ? `#${r.scan_id}` : "—"}</td>
                <td>{r.from_status || "—"}</td>
                <td>{r.reason}</td>
                <td>{r.created_at}</td>
              </tr>
            ))}
            {!logs.length && (
              <tr>
                <td colSpan={7}>尚无隔离流水。</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </>
  );
}
