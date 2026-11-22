import { useEffect, useState } from "react";
import { api } from "../api";

export default function Home() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api
      .总览()
      .then(setD)
      .catch((e) => setErr(e.message));
  }, []);

  const cells = d
    ? [
        ["在途水位", d.在途水位],
        ["待取", d.待取],
        ["超期待扫", d.超期待取数],
        ["超期隔离", d.超期隔离],
        ["今日已取", d.已取],
        ["日闸", d.日闸],
      ]
    : [];

  const scan = d?.今日扫描;

  return (
    <>
      <div className="hero-strip">
        <section className="ticket-hero">
          <h2>今日挂衣</h2>
          <p>
            票墙左侧是工位入口。先开票贴号，再沿工序推到待取，顾客凭暗码核销；逾承诺日仍待取的票由到点扫描统一改入超期隔离，隔离流水与待取页、水位同源重放。
          </p>
        </section>
        <div className="metrics">
          {cells.map(([k, v], i) => (
            <div className="metric" key={k} style={{ animationDelay: `${i * 0.05}s` }}>
              <b>{v ?? "—"}</b>
              <span>{k}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="msg">{err}</div>
      {d && (
        <section className="panel">
          <h3>今日超期扫描</h3>
          <p className={`msg ${d.今日扫描已跑 ? "ok" : ""}`}>
            {scan
              ? `扫描 #${scan.id} · ${scan.finished_at ? "已完成" : "进行中"} · 核对 ${scan.scanned} · 隔离 ${scan.quarantined} · 跳过 ${scan.skipped}`
              : "今日尚未运行扫描。"}
          </p>
          <p className="hint">
            待扫超期票 {d.超期待取数} 张。超期进隔离只认扫描落定；扫描落定后待取页不再展示、总览超期数归零，日闸预检才放行结案。
          </p>
        </section>
      )}
      {d && (
        <section className="panel">
          <h3>工序分布</h3>
          <table>
            <thead>
              <tr>
                <th>状态</th>
                <th>票数</th>
              </tr>
            </thead>
            <tbody>
              {["已收", "水洗", "烘干", "熨烫", "待取", "已取", "超期隔离", "丢失隔离"].map(
                (s) => (
                  <tr key={s}>
                    <td>
                      <span className={`badge ${s}`}>{s}</span>
                    </td>
                    <td>{d[s]}</td>
                  </tr>
                )
              )}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}
