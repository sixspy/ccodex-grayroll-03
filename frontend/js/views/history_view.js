import { api } from "../api.js";
const { ref, onMounted } = Vue;

function fmt(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

export const HistoryView = {
  setup() {
    const items = ref([]); const err = ref("");
    async function reload() {
      try { items.value = (await api("/api/history")).items || []; }
      catch (e) { err.value = e.message || String(e); }
    }
    onMounted(reload);
    return { items, err, reload, fmt };
  },
  template: `
  <div class="panel">
    <h2>变更历史</h2>
    <p class="hint">覆盖强制开带失效时刻时，此处同时留到期字段；缺时刻只落影子草案。</p>
    <div class="err" v-if="err">{{ err }}</div>
    <table>
      <thead><tr><th>动作</th><th>开关</th><th>环境</th><th>详情</th><th>到期时刻</th><th>操作者</th></tr></thead>
      <tbody>
        <tr v-for="it in items" :key="it.id">
          <td>{{ it.action }}</td><td>{{ it.flag_key || '-' }}</td><td>{{ it.env_code || '-' }}</td>
          <td>{{ it.detail }}</td>
          <td>
            <span v-if="it.expires_at">{{ fmt(it.expires_at) }}</span>
            <span v-else-if="it.action && it.action.indexOf('override') === 0" class="pill warn">无到期</span>
            <span v-else class="muted">—</span>
          </td>
          <td>{{ it.actor }}</td>
        </tr>
      </tbody>
    </table>
    <button class="btn secondary" style="margin-top:0.7rem" @click="reload">刷新</button>
  </div>`
};
