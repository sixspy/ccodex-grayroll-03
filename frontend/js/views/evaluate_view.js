import { api } from "../api.js";
const { ref, onMounted } = Vue;

function fmt(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

export const EvaluateView = {
  setup() {
    const form = ref({ flag_key: "feed.ranking_v2", env_code: "prod", subject_key: "u-1001" });
    const result = ref(null); const board = ref(null); const err = ref("");
    async function reloadBoard() { board.value = await api("/api/evaluate/board"); }
    async function run() {
      err.value = "";
      try { result.value = await api("/api/evaluate", { method: "POST", body: JSON.stringify(form.value) }); }
      catch (e) { err.value = e.message || String(e); }
    }
    onMounted(reloadBoard);
    return { form, result, board, err, run, reloadBoard, fmt };
  },
  template: `
  <div class="grid">
    <div class="panel span-5">
      <h2>在线求值</h2>
      <p class="hint">覆盖优先于正式规则；未升正的影子覆盖只提示、不假绿；过期或缺失效时刻的正式覆盖不永久命中。</p>
      <div class="field"><label>开关键</label><input v-model="form.flag_key" /></div>
      <div class="field"><label>环境</label>
        <select v-model="form.env_code"><option>dev</option><option>staging</option><option>prod</option></select>
      </div>
      <div class="field"><label>主体键</label><input v-model="form.subject_key" /></div>
      <button class="btn" @click="run">求值</button>
      <div class="err" v-if="err">{{ err }}</div>
      <div v-if="result" style="margin-top:0.8rem">
        <p>
          <span class="pill" :class="{'danger': !result.enabled}">{{ result.enabled ? '命中' : '未命中' }}</span>
          <span class="muted" style="margin-left:0.5rem">{{ result.reason }}</span>
        </p>
        <table>
          <tbody>
            <tr v-if="result.expires_at"><td>覆盖到期</td><td>{{ fmt(result.expires_at) }}</td></tr>
            <tr v-if="result.override_expired"><td>覆盖状态</td><td><span class="pill warn">已过失效时刻，不命中</span></td></tr>
            <tr v-if="result.override_missing_expiry"><td>覆盖状态</td><td><span class="pill warn">缺失效时刻，不永久命中</span></td></tr>
            <tr v-if="result.pending_override_shadow"><td>影子覆盖草案</td><td><span class="pill warn">未升正，不计入强制开</span></td></tr>
            <tr v-if="result.kind"><td>规则</td><td>{{ result.kind }} · {{ result.percent }}% · v{{ result.version }}</td></tr>
          </tbody>
        </table>
        <pre>{{ result }}</pre>
      </div>
    </div>
    <div class="panel span-7">
      <h2>正式规则板</h2>
      <table v-if="board">
        <thead><tr><th>开关</th><th>环境</th><th>类型</th><th>%</th><th>版本</th></tr></thead>
        <tbody>
          <tr v-for="(r,i) in board.rules" :key="i">
            <td>{{ r.flag_key }}</td><td>{{ r.env_code }}</td><td>{{ r.kind }}</td><td>{{ r.percent }}</td><td>v{{ r.version }}</td>
          </tr>
        </tbody>
      </table>
      <button class="btn secondary" style="margin-top:0.7rem" @click="reloadBoard">刷新</button>
    </div>
  </div>`
};
