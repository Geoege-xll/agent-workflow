"""验证目录入口的安全引用与真实安装，不把文本校验冒充模型执行效果。"""

from __future__ import annotations

import json
import re
import base64
import hashlib
import zlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from lib.business_confirmation_policy import read_instruction_contract
from lib.skill_contracts import BOOTSTRAP_TARGETS, expand_bootstrap_contract
from lib.task_graph_cli import export_task_pack
from tests.test_task_graph_records import graph
from tests.test_unified_host_workflow import HOSTS, UnifiedHostFixture


PACK = Path(__file__).resolve().parents[1]
TARGET = BOOTSTRAP_TARGETS["platforms/codex/AGENTS.codex.tpl"]


# 翻译前 85f84a7 的真实共享入口，仅作升级测试输入；不是模型规则来源。
# 完整字节摘要绑定历史输入，运行测试无需 Git 历史，用户中文区块另行逐字保全。
LEGACY_BOOTSTRAP_SHA256 = "801f43171c6ae6f04180c577560fb3afc9cee6721811e11d4644152741a5434f"
LEGACY_BOOTSTRAP = zlib.decompress(base64.b85decode(
    b"c-oa%TTfe88hz(ic+{7f2ZvD~tI<ekI&GsSYA%YRsv0G(ITTNfO>IMp)CUu=vB5WjZEgl*FqeebhJ=9e@#VjyXYX^)Q~tuNZ-2+e"
    b"bBoj$@MWL9zsvg8THBww#(vTQ5!d5j=-Grn_}umRtv|bd3<e|NNXRoiGGgY>pL%G;ljqKgr)It^6S<G=Z9DqHj-|!s$;bBA(_3nl"
    b"yT595Iu!h;=8fE%^Gx}l{uX^PGV<AHF42qGrKr`tHVdhd5x2|GV|RQ%O-4SpvtP~l{YEnr_D*V3o+q<fDC`RczWDrOJ7qM}MsLR~"
    b"Y|8axvz9bl$5?LYx>&9lt*Xo%idb9JuW`n`yVgb7x;PN&taY~VTXf#4S483^UhqP^7;(8|aY<GV%<a196vWGvxO!{9PRabGTrP;t"
    b"Ikpk?U0Lkd`i51n%8RaOT#Hs-WXec9JoBT<6WNRGYgtN~`4gGAk{cPbQn%`_?%kE8H&*M^XuY+TUSlIOb0#`#BALd)R%$_PU&!@K"
    b"qq`!iMWjZXs*J3od3pW<ncACaL?Acoc694Qv?SV5alC?jP5s!^Ym|6<L!^oyqB{s(u5RE#s!!_}!SS|KYqyKy&aUEIk*LaI4UyQJ"
    b"F%AG#ke3PT;@XPFP;vVpV{g8~Q>qh2r-zg{WXd2F6S-3^HeS=CrKmW|idak};;5U|m`5!Tf@rry;u2X>Bdy~_uKSl`UsLsaJEFER"
    b"XokI%7S*&WSXCy9=E@uMbmjgSLf|%`LRMqZXrBQt$dA7l^$Iqi095-BxK+o3IHk*nGDrYQBmk75o_qx1U??6uDe?`Y8ASuFhHf>k"
    b"u=4&Gb@V)HFPv~v$jDmgi1_CHG1tAZhYz``P9buqeV9M-YqOf4PoV0iic`Vy8NY^4LP7P<Jb5STTRcJ@zt0oKXTCr<;t6=QC(}W{"
    b"&pY?UL`VxyGB~}#Kt%f`(*I`C6BrLpOgsq&{Bwkh;u&KKtpgVBk5S>f>i~yL_E1Wc6-^NJlq_7_yNeYfwkX<VqrGJ{c6gK~5V?sp"
    b"nYhTl#YZ@kkc_J5FS+fQ47s;7z>1+Cn0xcI*VUoXDT!3eXrUXsgQW37WE)1WA~OlOLvMMWP(_)p6HH65Mf@F}vMblzF4@Q$oirbc"
    b"R5)NXg98B2s7cHf>IlRsQ%h#+n&vfu>1ttWu^#!zjRxWL>YP8JLpL(qEo(kSWRN%&xwKvA$x@jig54NX+)kNF5?oYiF+#``uWx@z"
    b"fXJnIiPhW1^l|B_r{$W}%Tqn{Ly=v^GOJU^EI-g@ecE#^L^Zvt+e=yWLzc0mfv15=LO2?hZOHsJH-K>w(k2|9(+>fKnJEoHc!N{Z"
    b"9&bd{56t5;*^HU5S|C7vjH^g=vA<|8)I{tAz~w}#V>qL7D)oxdT(&oJs(49J?-@<qER~Uk)yr9x6eXHm1H+iDo_Vq&vInBOXf#_q"
    b"bu<xKdpi!Q7xkpfyadG}Bd#npERo~>QTx>seKr6r(I)Ob3NDwcB9~$MH1##PQ$}Uw`X0(BVpj^Z=hg*^^qOm9N8@%hDmvE$qzzrx"
    b"_N_((bjDbvHL4<J@|Bs3b6qIXd{pAZMA2SamiaCq$HUK2<5}L5N~RVVdRktfwI_Cdo+v-FB9^y_nnACz#6S~_W}Z2TTB<m&50Vr!"
    b"gjtV@bm7i}NAhYzo}bC&F)C{`Yl<mf<5{i)rKyU<hydns=-AiayPo;{en6h<WHd<~h+85dO;g!ATqV~JMQ>fHP7&ly)7X9?noUO-"
    b"=l8KM%PL1E5_|S$6-iqAr=nc|_ROtCYT0fH&vH!MN@7mH<H6s@zWiR4P8c9uH4%@oj0{hU+COStH56E)k3+tQ7NWrVT}01BW!Gq~"
    b"$YzryPHhF16Wth(D=A^4W?UzY?vC}I^op6786G7w^bG*Ts<#L?^Ccj_NeV)&*2v{UvAQhcfI@{Tn}8MB<LUf2x~ANacS!qr#uw72"
    b"Flyl^o@qFfS#6x=Hd7Y6D|R#~S6<1tJv<FTS5g6r*nV`|{kLEMbU8&-?dW1$SCMroh@Ay-GS8?4oUP-yb)2-<Ps}4yL|!AZB-Zdy"
    b"Y!mn>K9+<JW&rL55}#eAN-0C(1Ut^F#Qv^W-kbG>XFUEv=!5Aeh03my`54+B8`BWyQnGePrl56f^y(lSQr%pGx5W+|pfZ0(GimA<"
    b"U{QGxC3a&=Q;M2;!Wp7|t*CY9^CIRLGHTuRJCOx*Cc#0d2<Qgm0KD)ZP*#eS0AxoyYwNQ9o`8@^7_9`DmY?E=K_Ezdl)?k2iXEr4"
    b"sbFXhPSL6mVHlk?6IP>o&MHL6W7XoQ`x3;erNk#G3kipf)NqrIzOCSMqj@Oz+Q^BIwYT!-5hNuecMfGMM`VB!pDkc#s=IGo3%Np?"
    b"*W>piw6JGZBge@u7yl-FehnQI&AM2Ah4Dbs8MT}!oWyXV&iv>ZFpXJ094IRMwArbf7yB4m)ySxPQ(-Bl($=>`V%@5o;05%P_cv1|"
    b"6wJ^siB=Dyq&KXhitrud_kIx>F&Z7sud0fv;-GuhL5xe}OxpGybtaoLt1WhGyoMTnbqKLQ1s>gIZ6^8LkBf4d;YZ@C!iVDnpGerq"
    b"hVGa$Rc4XByrFXCS73E1mf8XGzzJr%h-z^IvH1_qtKzkMS0F-E0q~gq<B$J!?eKddG_&E+@T3Q0G#Vy`4UhgZ=k^B2H8&ZraZhMG"
    b"Jo@n4+js8Vni~HTcckw^hYc|9LhMCIw{}b9>-7#&fB4Oqsjs35NMshKZrl?g#fEPSkz&KRRCJ@g$D6p_5l{G;8(RMC#;e+umS|-$"
    b"rw(6zh`(gi^Cbjtag)gAlzxyCrtg(aVbe=*)qFA&qVvkUvn+GV(G3NcxXd^BT;@0S=?oOM<`5o+BPqF3o4$|1+|w1OkYYFEc%J^~"
    b"qiA$%#IoEfqGe825wLPA703|87PDY`tG6v$M+o)aUCIL&9<urS_BuHy-pDaQ-4##=2|_K$&UM)IK$PHhz8|}L2NhR#KFvI8b=SmF"
    b"%hWfS35Xcd1x$}aVHk*50^hRNget(2nzf?UxM08dO)&T@OhVL+VSrJ4JN|NjQ+AaDav5ZKe~jcuIRYAF$K9x@hn?Kt4b21sS_lgj"
    b"&&u;XGAQa^DYp0Rjj}wch<3JrJ0_Q=AS2h(aN1OXY;k0SucH)wAD51o+gb#w`^cy1FTD{lNbrHZ)+J%dkx~z2ip5uCkMJR2j2<|X"
    b"y}W02I%E&t<FZ21Fv8e*NRvYY7rSIH4hwGR)f=;(Ez+Uts>-8HG*jFp(%q?mkQjW*dn!b#u9F*8c7<7-oQ$F+Wnk59Zsb?ja2Z^`"
    b"!Y&+{dYnhz^((%2yWKA5FWwFRgaGm&ud2#`B|i*R=y#FDV9kIg)KLS=%eQ7kjLSRT^7y3-pbND4<_gT<Bd4v56e4;$yg7`&7SdoZ"
    b"!lUE9@U$o5oy1X3)lrXb)9&Xw;cdvM(A&dRvvq_rGt$|4@JXLIV8-Vj*TTM^0)rDoVn-aW(1!cF7;gkFw|g?Z&(?t1{ZkRE-EJ6l"
    b"urFWq`O>c_hU^C!V%2v-l!B0R`%*`K;uth3;P(3_H1C|(uMH02+lIP(rtPD|;1)u6;><8#ePV0h)U;pOLQljO47ibp`)AKhd8%7t"
    b"xlA5kNkiY3Q}fleNRitcQ92`;RZwT|`iTSkd!Q43->epz8yq(9JWTMk_YnOn&QUDWzgW?2T_ODc9p&{0!&-1AGB|<7Of=eHNxHlD"
    b"#f-0}bcIqkBoG0G&?)f!>=P$|+#<dy%?(c!9Bw}xr&yb3-cik_!1;1QyZw(J3dd)>k<rKBJ^1#kJKsH~eGtTd^d|TmL>iv-P4{h~"
    b"yZ<A~4K{H4$Y1^dQW*Sx>877kNRz*C{hnC|v;1}BUp?RN+W"
))


class BootstrapReferenceTest(unittest.TestCase):
    def entry(self, target: str = TARGET) -> str:
        return (f"仅 Codex 首次编排时读取 [宿主细则](.agent-workflow/{target})\n"
                f"<!-- bootstrap-contract: {target} -->\n")

    def test_machine_expands_contract_without_expanding_auxiliary_links(self):
        reader = Mock(return_value="审批与 QA 完整约束\n")
        body = self.entry() + "[辅助项目事实](docs/PROJECT.md)\n"
        result = expand_bootstrap_contract(body, reader, TARGET)
        reader.assert_called_once_with(TARGET)
        self.assertIn("审批与 QA 完整约束", result)
        self.assertIn("[辅助项目事实](docs/PROJECT.md)", result)

    def test_unknown_or_cross_host_reference_fails_before_read(self):
        # 不允许 URL、父目录、绝对路径或另一个宿主的契约作为当前宿主的正文。
        for target in ("../secret.md", "/tmp/secret.md", "https://example.test/rules.md",
                       BOOTSTRAP_TARGETS["platforms/claude/AGENTS.claude.tpl"]):
            with self.subTest(target=target):
                reader = Mock()
                with self.assertRaises(ValueError):
                    expand_bootstrap_contract(self.entry(target), reader, TARGET)
                reader.assert_not_called()

    def test_missing_duplicate_unlinked_empty_or_nested_contract_is_rejected(self):
        for body, detail in (("无路由", "规则"), (self.entry() * 2, "规则"),
                             (self.entry().splitlines()[1], "规则"),
                             (self.entry(), " \n"), (self.entry(), self.entry())):
            with self.subTest(body=body, detail=detail), self.assertRaises(ValueError):
                expand_bootstrap_contract(body, lambda _path: detail, TARGET)

    def test_every_source_entry_is_a_route_to_a_complete_contract(self):
        for relative in BOOTSTRAP_TARGETS:
            with self.subTest(relative=relative):
                entry = (PACK / relative).read_text(encoding="utf-8")
                contract = read_instruction_contract(PACK, relative)
                self.assertLess(len(entry.encode()), len(contract.encode()))
                # 普通链接不是 Claude 的全文 @ 导入，也不是 Antigravity 的全文 include。
                self.assertNotRegex(entry, r"(?m)^\s*@|@\[[^]]+\]\(")


class BootstrapInstallTest(UnifiedHostFixture, unittest.TestCase):
    def check_installed_light_handoff(self, project: Path, host: str) -> None:
        """用已安装CLI承接一项明确局部修复，验证分发后的真实交接边界。

        复用规范夹具以保留Writer底线，只移除Light不需要的图字段。该检查证明安装态
        单包可运行与禁止父历史输入，不冒充模型真的派发了Agent或已执行任务。
        """
        pack = export_task_pack(graph(), "api")
        task = pack["task"]
        task.update(workflow_level="Light", goal="修复当前CLI帮助中的已确认错误",
                    input_contracts=["user:fixture，当前局部目标与路径已明确授权"],
                    acceptance_evidence=["实际关键入口与必要回归验证"])
        for field in ("depends_on", "blocks", "qa_scope", "semantic_locks", "gates"):
            task.pop(field, None)
        pack["approved_gates"] = []
        # 只规范化测试拥有的临时根，保留运行时对/var等符号链接父目录的拒绝边界。
        handoff = project.parent.resolve() / f"light-{host}.json"
        handoff.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
        command = ["bash", str(project / ".agent-workflow/lib/python_runtime.sh"), "-X", "utf8",
                   str(project / ".agent-workflow/lib/task_graph_cli.py"), "task", "--input", str(handoff)]
        result = subprocess.run(command, cwd=project, text=True, capture_output=True,
                                check=False, timeout=20)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(pack, json.loads(result.stdout))
        self.assertNotIn("tasks", json.loads(result.stdout))
        self.assertFalse((project / "docs/plans").exists())
        # 同一已安装入口必须拒绝夹带父历史；不能靠来源解析失败获得虚假的通过。
        pack["parent_history"] = ["不应进入当前实现者的PM历史"]
        handoff.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
        rejected = subprocess.run(command, cwd=project, text=True, capture_output=True,
                                  check=False, timeout=20)
        self.assertNotEqual(0, rejected.returncode)
        self.assertIn("task pack", rejected.stderr)

    def test_each_host_independent_install_contains_shared_bootstrap(self):
        # 逐个平台独立安装，确保共享规则不是聚合安装恰好补齐的隐含依赖。
        for host in HOSTS:
            with self.subTest(host=host):
                temporary, project, pack = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                result = self.run_script(project, f"setup_{host}.sh")
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                entry = (project / "AGENTS.md").read_text(encoding="utf-8")
                self.assertIn("<!-- pack:product-begin -->", entry)
                self.assertIn((pack / "platforms/shared/AGENTS.product.tpl").read_text().strip(), entry)
                # 用真实旧中文受管正文模拟同一安装的升级，前后中文用户字节必须完全保留。
                self.assertEqual(LEGACY_BOOTSTRAP_SHA256, hashlib.sha256(LEGACY_BOOTSTRAP).hexdigest())
                begin, end = "<!-- pack:product-begin -->", "<!-- pack:product-end -->"
                prefix, remaining = entry.split(begin, 1)
                _managed, suffix = remaining.split(end, 1)
                user_prefix = "# 用户规则\r\n中文沟通并保留尾部空格  \r\n" + prefix
                user_suffix = suffix + "\r\n用户尾注不得英文化。  "
                (project / "AGENTS.md").chmod(0o640)
                (project / "AGENTS.md").write_bytes(
                    (user_prefix + begin + "\n" + LEGACY_BOOTSTRAP.decode().rstrip("\n")
                     + "\n" + end + user_suffix).encode("utf-8"))
                updated = self.run_script(project, f"setup_{host}.sh")
                self.assertEqual(0, updated.returncode, updated.stdout + updated.stderr)
                refreshed = (project / "AGENTS.md").read_bytes().decode("utf-8")
                self.assertTrue(refreshed.startswith(user_prefix))
                self.assertTrue(refreshed.endswith(user_suffix),
                                f"wanted_suffix={user_suffix.encode()!r}; actual_tail={refreshed.encode()[-len(user_suffix.encode())-4:]!r}")
                self.assertEqual(0o640, (project / "AGENTS.md").stat().st_mode & 0o7777)
                managed = refreshed.split(begin, 1)[1].split(end, 1)[0]
                self.assertEqual((pack / "platforms/shared/AGENTS.product.tpl").read_text().strip(), managed.strip())
                self.assertNotRegex(managed, r"[\u4e00-\u9fff]")
                checked = self.run_script(project, f"setup_{host}.sh", "--check")
                self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)

    def test_missing_detail_blocks_preflight_without_project_writes(self):
        for host in HOSTS:
            with self.subTest(host=host):
                temporary, project, pack = self.make_fixture()
                self.addCleanup(temporary.cleanup)
                # 只删除临时夹具中本次测试拥有的文件，不触及源包和实际项目。
                detail = pack / f"platforms/{host}/references/pm-integration.md"
                detail.unlink()
                before = {str(p.relative_to(project)): p.read_bytes()
                          for p in project.rglob("*") if p.is_file()}
                result = self.run_script(project, f"setup_{host}.sh", "--preflight")
                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn("pm-integration.md", result.stdout + result.stderr)
                after = {str(p.relative_to(project)): p.read_bytes()
                         for p in project.rglob("*") if p.is_file()}
                self.assertEqual(before, after)

    def test_detached_install_resolves_routes_preserves_user_rules_and_checks_all_hosts(self):
        with tempfile.TemporaryDirectory(prefix="workflow-bootstrap-routing-") as raw:
            project = Path(raw) / "项目 With Spaces"
            project.mkdir()
            user_rules = "# 用户规则\n\n中文沟通；不要改动业务代码。\n"
            (project / "AGENTS.md").write_text(user_rules, encoding="utf-8")
            sentinel = project / "business.txt"
            sentinel.write_bytes(b"user-owned business bytes\n")
            # 本节点验证旧自包含安装的路由/更新，不是默认中央 CLI；沿用显式低层
            # legacy 安装 fixture，防止把测试状态写到用户默认中央库。中央 CLI 合同另测。
            result = subprocess.run(
                [sys.executable, "-B", "-X", "utf8", "-c",
                 "from pathlib import Path; from lib.install_workflow import _install; import sys; "
                 "_install(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())", str(project), str(PACK)],
                cwd=PACK, text=True, capture_output=True, check=False, timeout=90)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            entry = (project / "AGENTS.md").read_text(encoding="utf-8")
            self.assertTrue(entry.startswith(user_rules))
            self.assertEqual(b"@AGENTS.md\n", (project / "CLAUDE.md").read_bytes())
            self.assertEqual(b"user-owned business bytes\n", sentinel.read_bytes())
            targets = re.findall(r"\[[^]\n]+\]\((\.agent-workflow/[^)]+)\)", entry)
            # 必需四个bootstrap路由必须齐全；普通专业方法链接也可以存在，不按链接总数
            # 限制渐进读取入口。后续逐条检查真实目标，仍拒绝丢失或悬空的分发资源。
            expected_routes = {".agent-workflow/" + target for target in BOOTSTRAP_TARGETS.values()}
            self.assertTrue(expected_routes.issubset(targets))
            for target in targets:
                self.assertTrue((project / target).is_file(), target)
            # 入口不再常驻三平台完整细则，也不以机械行数/字节目标定义规范。
            detail_bytes = sum((project / ".agent-workflow" / target).stat().st_size
                               for relative, target in BOOTSTRAP_TARGETS.items()
                               if "/shared/" not in relative)
            self.assertLess(len(entry.encode()), detail_bytes)
            self.assertNotIn("installed-code-review-skill", entry)
            for host in HOSTS:
                checked = subprocess.run(
                    ["bash", str(project / ".agent-workflow" / f"setup_{host}.sh"), "--check"],
                    cwd=project, text=True, capture_output=True, check=False, timeout=90)
                self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
            self.check_installed_light_handoff(project, "shared")


if __name__ == "__main__":
    unittest.main()
