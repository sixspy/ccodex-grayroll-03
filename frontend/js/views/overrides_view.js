import { api } from "../api.js";
const { ref, onMounted } = Vue;

function toLocalInput(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function fromLocalInput(v) {
  if (!v) return null;
  const t = new Date(v).getTime();
  return Number.isNaN(t) ? null : t / 1000;
}
function fmt(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

export const OverridesView = {
  setup() {
    const items = ref([]);
    const shadows = ref([]);
    const form = ref({
      flag_id: 3, env_id: 3, subject_key: "u-7777", effect: "force_on",
      note: "客服个案", expires_input: toLocalInput(Date.now() / 1000 + 7200),
    });
    const promoteInput = ref({});
    const err = ref(""); const msg = ref("");
    async function reload() {
      const res = await api("/api/overrides");
      items.value = res.items || [];
      shadows.value = res.shadows || [];
    }
    async function submit() {
      err.value = ""; msg.value = "";
      try {
        const expires_at = fromLocalInput(form.value.expires_input);
        const body = {
          flag_id: form.value.flag_id, env_id: form.value.env_id,
          subject_key: form.value.subject_key, effect: form.value.effect,
          note: form.value.note, expires_at,
        };
        const res = await api("/api/overrides", { method: "POST", body: JSON.stringify(body) });
        msg.value = res.mode === "shadow"
          ? "缺失效时刻：已落影子覆盖草案，正式覆盖册零增，须带时刻升正"
          : `已写正式覆盖，到期 ${fmt(res.expires_at)}`;
        await reload();
      } catch (e) { err.value = e.message || String(e); }
    }
    async function promote(id) {
      err.value = ""; msg.value = "";
      try {
        const expires_at = fromLocalInput(promoteInput.value[id]);
        const qs = expires_at ? `?expires_at=${expires_at}` : "";
        const res = await api(`/api/overrides/shadow/${id}/promote${qs}`, { method: "POST", body: "{}" });
        msg.value = `影子覆盖已升正，到期 ${fmt(res.expires_at)}`;
        await reload();
      } catch (e) { err.value = e.message || String(e); }
    }
    onMounted(reload);
    return { items, shadows, form, promoteInput, err, msg, submit, promote, reload, fmt, toLocalInput };
  },
  template: `
  <div class="grid">
    <div class="panel span-5">
      <h2>单点覆盖</h2>
      <p class="hint">强制开须带失效时刻：缺失效时刻只落影子草案，正式覆盖册零增。</p>
      <div class="field"><label>开关ID</label><input type="number" v-model.number="form.flag_id" /></div>
      <div class="field"><label>环境ID</label><input type="number" v-model.number="form.env_id" /></div>
      <div class="field"><label>主体键</label><input v-model="form.subject_key" /></div>
      <div class="field"><label>效果</label>
        <select v-model="form.effect"><option value="force_on">强制开</option><option value="force_off">强制关</option></select>
      </div>
      <div class="field"><label>失效时刻（必填，缺失则只落影子草案）</label>
        <input type="datetime-local" v-model="form.expires_input" />
        <button class="btn secondary" style="margin-top:0.35rem" @click="form.expires_input=''">清空以复现缺时刻</button>
      </div>
      <div class="field"><label>备注</label><input v-model="form.note" /></div>
      <button class="btn" @click="submit">保存覆盖</button>
      <p class="muted" v-if="msg">{{ msg }}</p>
      <div class="err" v-if="err">{{ err }}</div>
    </div>
    <div class="panel span-7">
      <h2>正式覆盖册</h2>
      <table><thead><tr><th>开关</th><th>环境</th><th>主体</th><th>效果</th><th>有效</th><th>到期时刻</th></tr></thead>
      <tbody>
        <tr v-for="it in items" :key="it.id">
          <td>{{ it.flag_key }}</td><td>{{ it.env_code }}</td><td>{{ it.subject_key }}</td>
          <td>{{ it.effect }}</td><td>{{ it.active ? '是' : '否' }}</td>
          <td>{{ fmt(it.expires_at) }}</td>
        </tr>
      </tbody></table>
      <h2 style="margin-top:1rem">影子覆盖草案</h2>
      <table><thead><tr><th>ID</th><th>开关</th><th>环境</th><th>主体</th><th>效果</th><th>状态</th><th>升正到期</th><th></th></tr></thead>
      <tbody>
        <tr v-for="s in shadows" :key="'s'+s.id">
          <td>{{ s.id }}</td><td>{{ s.flag_key }}</td><td>{{ s.env_code }}</td>
          <td>{{ s.subject_key }}</td><td>{{ s.effect }}</td><td>{{ s.status }}</td>
          <td><input v-if="s.status==='open'" type="datetime-local" v-model="promoteInput[s.id]" /></td>
          <td><button class="btn secondary" v-if="s.status==='open'" @click="promote(s.id)">升正</button></td>
        </tr>
      </tbody></table>
    </div>
  </div>`
};
