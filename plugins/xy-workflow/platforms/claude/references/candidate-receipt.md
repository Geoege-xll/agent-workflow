# Claude local candidate receipt

This adapter covers a maintainer-authorized `xy-workflow@xy-workflow-local` directory marketplace on macOS with the default Claude account configuration, APFS recursive change tracking, and Apple's `mtree` supporting inode and nanosecond ctime. The stable Git installation follows the ordinary [registration check](pm-integration.md#核对已安装的可执行来源).

## Read the current candidate receipt

Use this procedure in a fresh ordinary session after maintenance. A previous denial remains binding in its original session. All native queries and subsequent helper calls remain subject to the host's normal permissions. If one is denied, stop the affected operation. The business session reads data and queries the OS. It must never issue a receipt, enable tracking, run the external Python verifier, change permission settings or switch tools to repeat a refusal.

Run the checks yourself once for a contiguous batch, keeping only the receipt id, SHA-256, roots, deadline and result. Read the small pin and receipt. Keep the two metadata specifications out of model context.

**Bind the actual session.** Use the host's loaded identity: source `xy-workflow@xy-workflow-local`, version, and physical path. The native `system.init.plugins[]` entry exposes `source`, `version` and `path` in clients that deliver the event. A host-delivered Skill Base directory can corroborate the path. Require a unique marketplace-qualified source association. A guessed cache path, plugin manifest or bare role name cannot supply missing host identity. Stop on inline/`--plugin-dir` loading or a nondefault Claude configuration.

**Read independent evidence.** Use the system account record's home and the fixed `Library/Application Support/agent-workflow/candidate-verification` subdirectory. Verify literal physical paths, account ownership, no group/other write or writable ACL on the ancestors/materials, and regular single-link files for the pin, receipt and two specifications; macOS provides `/bin/realpath` and `/bin/ls -ledn`. Read `pin.json` and `receipt.json`. Require schema 1, a UUID id, the current plugin id, exact equality of the full `pin` object, and `issued_at <= current UTC time < expires_at`. Compare `boot_session` to `/usr/sbin/sysctl -n kern.bootsessionuuid` as a UUID. Compare both specification SHA-256 values to their respective `roots.*.metadata_sha256`. Only the small metadata specifications are hashed here.

**Bind official registration.** Query `/opt/homebrew/bin/claude plugin marketplace list --json` and `/opt/homebrew/bin/claude plugin list --json` in the current project/configuration. Require one directory market named `xy-workflow-local` with `path` and `installLocation` equal to the pinned physical market, and no alias for this directory. Its physical `.claude-plugin/marketplace.json` has only that name, owner `{"name":"Agent Workflow"}`, and one plugin `{"name":"xy-workflow","source":"./plugins/xy-workflow"}`. Require the unique enabled user-scoped candidate. `projectEnabled` must be false or absent. A disabled stable registration is compatible; another same-name source or active override blocks this branch. Match `version` and `folderVersion` to the pin and session. The physical `readFromFolder` must be the market's `plugins/xy-workflow`, and `installPath` must be that root or the default account cache `.claude/plugins/cache/xy-workflow-local/xy-workflow/<version>`. Match both to the receipt's roots and the actual loaded path to one of them.

**Check current filesystem evidence.** Substitute quoted literal physical paths. Run the two specification hashes together. For each distinct root, use its corresponding fixed specification. The device, inode and positive `gen-count` must equal the receipt. `mtree` must exit 0 with empty stdout/stderr. Read the counter again after this metadata check.

```sh
/usr/bin/shasum -a 256 "<trust directory>/read_from_folder.mtree" "<trust directory>/install_path.mtree"
/usr/bin/stat -f '%d %i' "<registered physical root>"
/System/Library/Filesystems/apfs.fs/Contents/Resources/apfs.util -S "<registered physical root>"
/usr/sbin/mtree -P -x -f "<trust directory>/<read_from_folder or install_path>.mtree" -p "<registered physical root>"
```

Before use, confirm the fixed receipt id and pin are still current and unexpired. Keep only a short success summary. Recheck after a reload, restart, reinstallation, receipt change, or gap with uncertain file continuity. Examples of a blocking result include a changed APFS counter after a same-size edit, an `mtree` execution-mode mismatch, a different loaded root, and a host denial on `apfs.util -S`. Report the observed failure once. Maintenance and a new session can renew an expired or stale proof.

## 安装或更新候选

维护者从冻结提交取得本仓的 `scripts/verify_claude_candidate.py`，从可信发行记录取得 Claude 插件主包 ZIP、摘要与版本。在系统账户主目录下建立上述固定信任目录，目录权限为 0700。将核验器、`claude-plugin.zip` 和 `pin.json` 独立安装为当前用户持有的普通文件，权限为 0600。固定记录使用以下结构，替换示例值并核实来源。已有 RC2 的旧核验器须在维护阶段更新。

```json
{"version":"<版本>","marketplace_path":"<已登记市场的物理绝对路径>","sha256":"<主包的 64 位小写十六进制摘要>","source_revision":"<可选的 40 位冻结提交>"}
```

安装或替换候选后，在维护终端用默认 Claude 账户配置执行下列命令一次。维护者选择符合本次测试窗口的 UTC 到期时间。该步骤为两处登记根开启 APFS 目录统计，核对完整 ZIP 和两份载荷，并将当前文件系统证明原子写入固定目录。

```sh
/usr/bin/python3 -I -B "<固定信任目录>/verify_claude_candidate.py" --expires-at "<YYYY-MM-DDTHH:MM:SSZ>"
```

收据受本机账户、引导会话、到期时间、市场登记和两个物理根约束。更换同版载荷、重启、元数据变化或证明到期后重新核对，再用新会话测试。维护失败应查明诊断。自动派发和系统命令是否获准，以目标客户端的实际工具结果验收。
