/* 具体HTML的同步文件入口。必须由prepare放在所有业务脚本之前：父文档立即终止
 * 原解析，业务只在独立file子页执行；整个发现过程只加载经典脚本，不依赖file fetch/module。 */
(() => {
  "use strict";
  if (location.protocol !== "file:") return;
  const source = document.currentScript?.src;
  if (!source) return;
  const mount = new URL("./", source), assets = new URL("assets/", mount);
  const child = new URLSearchParams(location.hash.slice(1));
  const nonce = child.get("xy-file-nonce"), name = decodeURIComponent(location.pathname.split("/").pop());
  if (parent !== window) {
    // file只读nonce与HTTP控制token完全分离；父窗口还会验证真实window、page和null来源。
    if (!/^[a-f0-9]{48}$/.test(nonce || "") || child.get("xy-file-page") !== name) return;
    window.XYFilePageContext = Object.freeze({ nonce, name });
    const script = document.createElement("script"); script.src = new URL("file-page.js", assets).href;
    document.head.append(script); return;
  }
  const state = { name, originalFileURL: location.href, mount: mount.href, assets: assets.href, catalog: null };
  const fail = (message) => { document.body.textContent = message; };
  window.XYFileDeliveryEntry = Object.freeze({
    state,
    receiveCatalog(value) { state.catalog = value; },
    receiveShell(html) {
      if (typeof html !== "string" || html.length > 1024 * 1024 || !html.includes('id="review-workspace"')) { fail("交付工具损坏，请重新准备交付入口。"); return; }
      // 唯一模板来自受管工具；只改工具资源地址，绝不复制或拼接第二份业务HTML。
      const resolved = html.replace(/(src|href)="assets\//g, (_, attribute) => `${attribute}="${assets.href}`);
      document.open(); document.write(resolved); document.close();
    },
  });
  // document.open在解析期不能保证终止原parser（真实Chrome会继续执行旧脚本）。
  // 同步写入plaintext让剩余原字节成为不可执行文本；异步可信shell到达后才替换文档。
  // 标签无结束符是HTML tokenizer的既定语义，禁止改成可由业务</template>逃逸的容器。
  document.write('<plaintext hidden data-xy-stopped="1">');
  const load = (filename, next) => { const script = document.createElement("script"); script.src = new URL(filename, mount).href;
    script.onload = next; script.onerror = () => fail("交付工具未准备或已失效，请重新执行prepare-delivery。"); document.head.append(script); };
  load("catalog.js", () => load("shell.js", () => {}));
})();
