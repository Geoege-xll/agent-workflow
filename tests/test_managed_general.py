"""通用规范单一来源迁移：只操作临时项目，保留项目字节与原事务安全边界。"""
from __future__ import annotations

from functools import lru_cache
import importlib
import base64
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zlib
from unittest.mock import patch

from lib import install_workflow
from lib.standards_baseline import COMMON_BEGIN, COMMON_END, common_block, common_span
from lib.validate_project_config import validate_with_profile
from lib.validate_project_docs import validate as validate_documents
from tests import test_unified_host_workflow as host_cases

PACK = host_cases.PACK
# 两份最小历史输入只作测试数据：旧 UPSTREAM 证明整文归属，旧索引证明链接清理。
# 它们不是规范来源；通用规则始终以 Skill 为唯一 authority。测试不依赖 Git 历史。


LEGACY_UPSTREAM = b'# Upstream and Second-Development Standards \xe2\x80\x94 {{PROJECT_NAME}}\n\n- Domain: engineering\n\n> Define protected upstream/open-source boundaries here. If the project has no embedded upstream\n> source, state that explicitly instead of inventing a protected path.\n\n## Boundary declaration\n\n- Protected upstream roots: **TODO or not applicable**\n- Allowed extension/adaptor/overlay paths: **TODO or not applicable**\n- Direct upstream edits: **forbidden without an approved exception | allowed by project policy**\n- Upstream synchronization strategy: **TODO or not applicable**\n\n## Exceptional change contract\n\n- `[eng-upstream-001] [hard]` A protected upstream write requires the matching exceptional approval,\n  exact patch surface, reason, rollback plan, upstream-sync impact, and verification commands.\n- `[eng-upstream-002] [hard]` An exception authorizes only its declared paths and does not weaken\n  unrelated engineering or design rules.\n'
LEGACY_INDEX = b"# Standards \xe2\x80\x94 {{PROJECT_NAME}}\n\n> Canonical directory for enforceable engineering and design rules. Keep this file as a concise\n> index; detailed rules live in the linked leaf documents, while approved prototype evidence lives\n> under standards/prototype and is read only when it applies.\n\n## Usage contract\n\n- Every rule uses a stable lowercase ID and declares `hard` or `advisory` severity.\n- Normative Markdown leaves live directly in the configured standards root. Design leaves use\n  `DESIGN_*.md` and `- Domain: design`; other leaves declare `- Domain: engineering`. Group links\n  below by domain and describe applicable modules/paths; do not add engineering/design/references subtrees.\n- PM Task Packs select the smallest applicable leaf documents, bind their current fingerprints and\n  rule IDs to exact owned paths, and never preload the whole standards tree.\n- `GENERAL.md` \xe6\x98\xaf\xe7\x94\x9f\xe4\xba\xa7\xe4\xbb\xa3\xe7\xa0\x81\xe5\x8f\x98\xe6\x9b\xb4\xef\xbc\x88\xe5\x8c\x85\xe6\x8b\xac Trivial \xe4\xb8\xbb\xe4\xbc\x9a\xe8\xaf\x9d\xe7\x9b\xb4\xe6\x8e\xa5\xe4\xbf\xae\xe6\x94\xb9\xef\xbc\x89\xe7\x9a\x84\xe5\x9f\xba\xe7\xa1\x80\xe5\xb7\xa5\xe7\xa8\x8b\xe8\xa7\x84\xe8\x8c\x83\xe5\x8f\xb6\xe3\x80\x82\n  \xe6\x89\xa7\xe8\xa1\x8c\xe8\x80\x85\xe9\xa1\xbb\xe8\xaf\xbb\xe5\x8f\x96\xe5\x85\xb6\xe4\xb8\xad\xe9\x80\x82\xe7\x94\xa8\xe7\x9a\x84\xe5\x85\xb1\xe9\x80\x9a\xe5\xbc\x80\xe5\x8f\x91\xe8\xa7\x84\xe8\x8c\x83\xef\xbc\x9b\xe6\x9c\x89\xe6\xb4\xbe\xe5\x8f\x91\xe5\x92\x8c\xe7\x8b\xac\xe7\xab\x8b QA \xe6\x97\xb6\xef\xbc\x8cPM\xe3\x80\x81\xe5\xae\x9e\xe7\x8e\xb0 Agent \xe4\xb8\x8e QA\n  \xe5\x90\x84\xe8\x87\xaa\xe6\x8c\x89\xe8\x81\x8c\xe8\xb4\xa3\xe8\xaf\xbb\xe5\x8f\x96\xe3\x80\x82\xe5\x85\xb6\xe4\xbb\x96\xe5\xb7\xa5\xe7\xa8\x8b\xe8\xa7\x84\xe8\x8c\x83\xe5\x8f\xb6\xe6\x8c\x89\xe4\xbb\xbb\xe5\x8a\xa1\xe7\x9b\xb8\xe5\x85\xb3\xe6\x80\xa7\xe9\x80\x89\xe5\x8f\x96\xef\xbc\x9b\xe7\xba\xaf\xe5\x8e\x9f\xe5\x9e\x8b\xe8\xae\xbe\xe8\xae\xa1\xe4\xbb\xbb\xe5\x8a\xa1\xe5\x8f\xaa\xe4\xbd\xbf\xe7\x94\xa8\xe8\xae\xbe\xe8\xae\xa1\xe8\xa7\x84\xe8\x8c\x83\xe5\x8f\xb6\xe3\x80\x82\n- Subagents must follow every selected rule. A missing, stale, or incomplete applicable rule set\n  blocks dispatch or QA PASS; \xe2\x80\x9cread on demand\xe2\x80\x9d is not permission to ignore a relevant standard.\n- Update current rules in place. Git retains history; this directory does not record task logs.\n- Maintain stable topics: extend the existing section first; a new leaf needs a justified independent\n  boundary, not one rule or task per file. Keep common rules authoritative and specialist differences\n  scoped. Apply WORKFLOW's `Standards document granularity and maintenance` without weakening the\n  reading and coverage contract above.\n- PM assesses/adopts design-rule changes; UI Agent maintains authorized leaves. Initial adoption,\n  incremental changes and full visual replacement update only their approved scope. A feature-doc\n  no-op does not imply a standards no-op; refresh affected consumers after rule adoption.\n- Normative design rules live in leaves, not a duplicate HTML index. Adopted rules do not assert\n  that all production pages have migrated; use verified feature truth for completed migration.\n\n## Engineering standards\n\n{{ENGINEERING_STANDARDS_INDEX}}\n\n## Design standards\n\n{{DESIGN_STANDARDS_INDEX}}\n\n## Related controlled truth\n\n- Current project and feature index: `{{DOC_PROJECT}}`\n- Current functional and architectural rationale: `{{DOC_FEATURES_DIR}}/`\n- Prototype evidence, when configured: `{{DOC_DESIGN_DIR}}/prototype/`\n"

# 以下压缩数据只是不执行的历史升级输入，并非第二份规范权威。
# 一次性取证来自 85f84a70705550fd47feb68eed544c1f9f9c9b9d 的三个真实内置来源；
# GENERAL 的受管区沿用既有 2300f72 资源条目版本，保持历史完整区块 SHA 证明。
# 仅保留既有升级测试所需最小旧壳与真实条目，避免运行测试依赖 Git 历史/浅克隆。
# 每份解压结果绑定固定完整字节摘要；当前英文规则、标题和翻译不能重拼这些历史正例。
LEGACY_INPUTS = {
    "GENERAL.md": (
        "7c0857fdde42fdf2ae20d8ddff9ebac219015c171fd6a2df89661e407040d3f8",
        (
            b"c-oD8TT`1^dhWe{g?7!|u6Sm;bDpGjRo6^1Gqq=u&LpY1NTtfOt?qH!4c?gc?A})rAdo;p0&_lt!NS-eurUZpz>kT(gRc57?B{u("
            b"^(}q2$z*P9A-=;}@8Nl$_ptau=2zLT2JU~C$qs(?a4?%4emMBmox7Qz4Sh54aPTMZeT%Q}{Tsfx`xHNa`SAY0$itz*yFdQ%C;y)L"
            b"x8Ds6Klt~1neNq1G=I=-KMPvV;zmBK9EbCbu$+%p$9somezSNPbgJKX)`IG6G;<OZPw=Z?_Nv?73zr)~Zl#wiecveu)doJ`QFk&K"
            b"JuNui?5!01)A*L_>Ho~(fs@_#IX(pCLRef34|al$rMNs6teyR5ZnS%|5iP9X;;?w}eW%*nxs2A1gH9_bp5rrK)NNLJ?dAA*FD%vL"
            b"opMk(=#3p{J-Ge9+VQ9T9fyr-w|N-NZ*^PsZu@z(oySVCvp84iw)VR1<)FG0T%88bDtL3aJsEC}2kjQt5_J~i#%x%u1yfty<~(*B"
            b"-_)=K?3nv&KMOb4vB2KSc(lHSXX?gob0%ER1t-;@)(EB!@SI>`E*jgy)`P;^-u!V;*bl1DC3}cDu0QWhP6eCO+Pd@;G%kbIJOy8E"
            b"Xx~x}cMN$q_qd~@Qq-#V#;$s~)%a#IbMOCtclV2LA3k~@S$ubotL)`Q`MBZ)^n%@nGy8buuO5E&yAeF460B{9M|+ZX=I_6K^e7Xo"
            b"T|-lGeLN`6Va43)^y}!=bmpHv!&akK1KJFCo>NmBD<O0`vxTLH<x)@^k0%eK(>8aKtQD&d_9|S!)w7^fiLakw^WAnOTrY(SMJz9o"
            b"LOH@3PG*CfLT^2Xm+E`0Fdn-Ko}WbZli;`vP5c3k|7l9&SdJMZ<koGru%YhtM*MCun4=iO`EyuqIQ`P8sZfA;v}9U+p{ONmjq!_#"
            b"Xl)S-G&3*YY0|ZSa(sOmEtIL;wawsa4(8ljUFXj1MsBP69KXHQz~dMB@N_iZ*$>}M$BhLVduJI72um-6(*>9)*WkQ|dZ+DAR_Ri>"
            b"V6TqH_9iRw#cXe<9XHOx<(Y8tB-q{5tLbosi|*C4-t(E>%1izznV1r2-ZPD0cPywb2j#_}(TOL|yh4J#Q|uk<p}#I)0}r%R$cGlu"
            b"u1D=7Toa$|$2arA#Xc5bONEwJyH^#y3wHZF2dM`6$@uu1&oOy+Z}9L+e6xlPVpHMLwmyeT=ahVYU6z7<;WGD%i$-ug9$cQoelwr{"
            b"+UcUnYoe=TO1`=sOl^ltyL`p#op9l#+nnmH)Tm7}C@EKN0!Mbnm6&00a*FqcN4t13t-SjAuQTCxlP*}Bku4-{SLy9;1ba~C7Ez&k"
            b"Xj?hyUd>3x*jzY&2`NgSM7L%Mo*ESQ!o?#3L$Y1DrEDjz=Yxwk!Eq^mUbx+f@$P%W*)Oxh*}?nSCqH`6@SoftdYt{?HxKR!D&tdV"
            b"y&_+xXryve9x=;&IXK=4xAv(dIsQ+7iB11vXy|Lahxgp@hThr)_Si?A#Ot19?+<53p1dDa{vnGsW$q7s^UcGNjJx7bGWhR7c5vk3"
            b"z$5(dc=+Mdfst(H>+E;<X=Lc@>>&Oh8qN$4{66_5-v3}=WZ-Wy-#*D^Mt+yY_e1}Yy+3ky;4wZu%|1Y|d-`yAXz&|6miOvanQsOL"
            b"2foS<|M1S8AN(NmYy07Wt!8NO&Yi#gA9wF&@Xg@J-QN!lfBog7q2K=mKV^pp9^KV7Klvhy5SqDr_kZ#Jpl}LH2|78%Kj0t&)tx)x"
            b"`s<+FisnyY>)osM@LgW&3RVuH_E|W!$ADOw1RTST0Tbcc8Jq#oif|GipWt4EJeZ?{_~x_VbW=(RCRT#=16@GNS{=`P?l%48arQp-"
            b"oEiT1QT7R}?}&Q1({1l}o70BScB{p*XswBOL9m=!!xCtq3q|_Z;)&kbd$9=DfG_a1TeYZO@fRaz!6?FJAzV38Y@*{7H-h>!kO3FK"
            b"YUxC~jBdfnYPf!=AVq_E*$PfaX-XISKpVh6J$;4`!Q1_I@j;@D&$i;T=h!sB%JGGriExwbfT(!2zz>KaHDU;{1)y4~#>dBi?x=Jb"
            b"9#3_ftHIPxG<A;PWAgX`bQZM{pmTBKf)br8XFmJ<ml-)%pAt#e@7ryf6i7l6XXY3G@-Lrfg5zCacJ!)Y=vCosUo{8|dyBdtJ{cpf"
            b"FP&5UN!)M%fAI$B;#Oq98NS)UH$klk-<O!(jV6BBR#?ixEJTlFRmL(>J4>wx59t*uCi~G~s}=3!g7uSNBL}hdN@wB580B|fz$^HT"
            b"p^dSL#qhisuG8(Qv{p4JE<wrs{H#I?sy`1mYY<`3TEN45^DA+q5nsIyE4#3@xUny(0vuqD!QOaOo1n2I_k!W!F1P_*rB)1T<!I*^"
            b"F+teGCrDz8mk!`d`_YTGS<1WK#x5h<OdV^3Uj@}f)y5-v`}L9|8St)|eLYI+bov4Zy*$^G<C~RkYt63^0ioO3=JVmYh-M~F5-77N"
            b"XJQCh2nfqFSaX~&!%iVF7%$&aa2EZsHT^}3THAVM{h%QFG1%G)PV&GC=q(z(w9q(;5Cs`)6+e>nsQ1lj+R1uJEGl~2hV}_4@;3W2"
            b"xvUIo2@i-HNAW>U7ii_w^3hUw{7&+x>2B{3#!Ydwmc2y~Xsm#7zEJcU*JaWaFh;RKFO>mMdQ00;>qWS+rMJ5!f!(~wa{<qDh%4}>"
            b"aP7ti4zF>Sc$iSkK^bbmamlpkTY7Ui-JxzR<de7Io6<DE#VxajYjP5p@$Yfob-BeQi{ZU*4s@V;9uk!yYrPE1oo&z{Zm68^UKU7z"
            b"=E_ceCg47U6un#C4o=3kLfgb7(9>OcaS@hoXr8sQL{3gWc?bzPJ;2Oi(X|;64)P>13;R_#Q<SHMXV-wDAlISiRTe;@sNs`Yu)W|k"
            b"M|If(_!d(ONFErE)RF+`s0>fW25#b@HbGA*JlV*a94@|ii-(vTO1-&bp(=Qa6UDoHbU<WMbaD0!95S!E)f@gYMZ&=b+pRus7WSi8"
            b"D^h#{m;wg`*CbHnL_(EvNzHT^qk;a%=-@5xavDW4SDgwvqd~K&z4arQA+VktzA+CnLM<g>^*<dN92p*Z^e8+0qu&gD3u=;<n7jd^"
            b"ko}tKxqZdmaQ>R1SJn$K-kpG(r_C6@RoW?~2$Nv0z1+6;0WS=mzqQTLJcQZq;qWIzxS%%cy(e5f>#e_WUJIOqLQU`5`fa-S<j>yM"
            b"#qK5^EQZ>>Mw$bjlH}s{5>k)8c7Om5VE4vh>(Dnm5E)M}If2|8@fk?#pwjXQ%Y>c<lP#|=KvVa!M1w9hz?n>lYrXut;QG*o$m*2f"
            b"%Q5${25{c{SWtTf*NQqXK^BBON^yv9&9UHQo(!$<mV0W>q_aKV{`v(kt5uLU67dSJLF%M;7B%2$mh?C~1V|q3i?R7ifS0?443c?n"
            b"#E3D2f<c+qW5I=qG$RfSSSl<bz*VVrlNA=vr7k(9;c1H&CL%^tlQb;(yM?!;N*ZD*$diD#Vd*+eIimKstF{;;bIBr;t-K7>n~vUV"
            b"K(hyP2$vhZ$yp>gmZ$88NOPT^=gDFl6OgJ<*wnEf+$`}eN6W$J0iU@shLo%CeTLL&pW$7)#<C#>CbMS8E~<yB1le7OxH33!bsB2W"
            b"wkBu`+dJ|3+jK#}+aB|KF&48u5@9)#5i?h107SxdXSN)&n{Wu(K29Y}1BS<7v%eH>cfc7$ljNvayq4X|wd3pAeh`BBwF`KA_;vxH"
            b"+3j??R})%{A_UEHy%nxBfa6xoI;E*6+x%GPf0fd?NmSscM~cnUnfF#9vkxMzdD8sH-kFvVTu`i2d`AH6+yWT2e&A@D%x$tIqjMpq"
            b"c%r-dyhG+}a{a!u`p>_A_~l3jtct5DmpoaJPat#XEuFzyqxK{r-|3<J+w2$ao~YH34F{7~Fcl)d*)|@*<nHm%lYuWDWzB<U7+~}w"
            b"v++JbUSaO8H^Q!!W28YSjXEy277h?|8HKN>4cnRVr`HUUi|wm;;jzt1ZL35DvkS&hBP0YH+&hbfZIREkrnS6u8e{j;j)LL@P>qO!"
            b"6q4CP-;OA^$^sIUe(H5>i!?-$>p)+94#Rx2ERzhbc45EDB!c3a)hJ0|GWY&<<l&<y_pq*ezsNp%oE^SLQife(6WXN`455{@?F+i%"
            b"UxcmW>-gB-*{OaETc7;+y}Dc)s(?Xw0#luGUg;+bP|gya{8){y!NFEp5Zj}Nvu4|xBlK9HCR(Majd8|4=<v73V$xiXvNRH`8i(a7"
            b"mRB%lFg;74;U=7>p5u!HNmLaicnp=3E70CMIZG0Z87aV2s;~%Gj5(i5UoS8UpH*-H09VXZ0IE_A+>0?%cI2W$C8z>8W*xm%LC?6G"
            b"HzE%o4my)^d*9*Af0$$7b=8KCqupj3_#uJ2Fm}BZPEA3)45A=?g|~ipUW}?Cd8+6=fK~tYQLsG`)f>PD!PUokosUCYn7OwW>@k$!"
            b"doqz$Vz9Fr-_R#S&_v#OJ49D?QG}M`GaQo=oe5mkNC2w`=K9d}$3=-?f|z<Mhe|h2j5?`r;h=DD70*y`_s&6e?U4_-lwf8HpN)Q$"
            b"aXYdCiqM3|9VEi*tzLt1^;YLC9nPn1A1tVQc}gU*Yb1Wxs_{r|6}@!E0)3L39q&;{h<8=!WC9P@I)Ruh?!LKkVzywwg{9DnNMOOn"
            b"C6dz<cmiK{c@DUNwy`xDl+{C$a`>ne$QqRa6TYW@5bK?it1`yk!cEY6fxY7{J(-bdk`$Tn{!gD}RH%m_)F1G+5h8r<o{%!<wxivd"
            b"s5I#rkAREVRh?B;O5v+7?(4&7rXk^yqnuQwP8Fqn1mIm0E4PrgkIaLVY~aDuhfjuvzhgPcsy1P+PO`sE_X*z~IEhab;{56dsx@<2"
            b"2K9_{FCb-a8ELnYI+^4kzNK}atJBm?@!@!tMPxX5d6G29?B7+jmX3S7%e>u;L+sY2+VFHBKz%gGSA+d4uEYwy?2jxRAf+cOQiL~f"
            b"rabM{>X;BM#S5wp>RWw0OR*Hy6?SfwTdG&1j>pHPvvBGvJ|$UIoWmm_A?r#W!k*QHv5FR%yeq8itw!}q0*84I+rARQo~7-85!ZYT"
            b"6pDp4^AVOpI}6NHRZLBVHJ@EOUOhwOijEeeg?&CY36<<Ns1uSZA~6KbgNROfh*cj6#FD6K&o`bi9*({BOh{Eh26)75m3XmPt0l_7"
            b"6@Gnic3j#~&6()UHT>)2X#8mk&^)WR?j1!WzgFC!<n19a7D&?NCM?;wnxPES0ruK<Z?(paAkO4E2?yFmCfL2%3G)rBYaK@Istc0G"
            b"t5~Nq!*Z#=61zQ|0gF9KO1$~rP75#PtFPujRcZCLB8X9M?Hm`&@7)Ku@7}4(D16=4z8*rQm_}G<Cy1@}xxgl<^EGa9dpE@E7r~yN"
            b";6^P#buAZia~<zPdJ(=+ms;&y!kQH^XfU;g$^_Qs`LK)WHIwdGpOcv@8)Lj|%ttem)<0&_4z*w_1kuT=B7obR6^<wd)0;6NEM%G~"
            b"*IYR+R$$r+s6uhCcJ=YYg)^~i2mt<Mgfq`>Rq;IDIRN+a_R9)btE^vz?~ZY?w&mJPwmf>6tsg!V9WSL3ytlCeQH8BtKouiH5tN0k"
            b"4PD7)TYx7Bit{;ET(<YRFX<>rS{58F!FIaMH^!Dmjgs<Ft|>dg{d!v7ze`<St3CL%mApqhSq<8=deF>EuzcDH4V<4BZcW!dP4}Re"
            b"&Y3Hy1ZZZbZv<6jo8#w7vn`!IXGEMU<4Ro9S83vGTD33b6RPmc>QwyhB0Spl%!iJuo}!X!JWwK36JEfog}EJ<ed&~4ft3U2#`b(m"
            b"@11C+C34Po8{tM}S~zOZ=s138kELrZZR>VYveY)|Ezb(9j3PE6v~9k&))MbZ>dTI~`M1lEy;vfAhHWMk&OwPMZz`!ALzxFY&e9fa"
            b"W`oebv5la4ONR32sU-VkBDw;$uKT>Xj}(Tm@6EHUZ6fEUZ$a!gYoNz$uH+lhQ7K(ykLwdEOEFO1>@bE|+YaFvKSG`^-LQ(ISF|IV"
            b"Nnyo9k{C7A6fad(wYA*Ab%tDR1vmw?N=mOunR!%?BH-HOgX;#)6uT{ptXA#`7pmd-mP@Ii9puW#Mb|@Its!Ue5F+>sCXXbRZhJ2("
            b"l`Shd?6z92R5`H%F{)bRt2466TZuuco1z+b^!jzTSz=Mc^eK)?Xk8(qYT_oW&OsqTsp6~3z+pE%VU;defn)v7DA@c|9Z3Yh0iyLU"
            b"!j1i~#Tr+9+=Rvq5NT6>j3O!(*$=KxIl5P@;YU~7OhhGE5tQiq2#{pOwB9@smgr^;W3dRItFws)i?*V_xEn=2d8nBVRao@EetLgW"
            b"MWA86Xza!Hztr6Yuh?m^gW{Ugq_l}7N8NahVYh0VP6A8k$`Q5Y_aa@p>KT+vNzI!HEv3s~^46}vCx7{2C0g#`3RW=R&S-dqjG-+Y"
            b"@$lyxnCe?nC-26g90b^K{+c4RN;Bd`ICn(20ozL4iR9J#Yo^KF-g3b{@cHa6!f9_d0b#w>sw!aV)Q8+^V=K;;{d@IBrbP8N$EcE$"
            b"7rXpPdarq>c=r{*v?O1C$ji3&<HoM&q1-HbwFzRvz;v_4Y}uLuijPvY3etYaEIfK1G@Duv)!sQ|DYRH~e8l9yKB~Dir-B+bQe$LU"
            b"MGed3bH05;K(xy^*=7dLb=tCRrme={Zo@S6vs_yt$~lU9SeNXe0#bQ>{w63SQ#(oOLg3z8WgA)RnZFM9>dfJ<t`us?uxgtC1-@cw"
            b"8!shvUKg}Gaj{zs>aX6<yRaD7$!{J>0-8fI5>nxhCLdO9lK`o52Dg*SJRD{iS`jny9L(xRO3QFqd*0jPlMTy6u@DltStQx41k8KR"
            b"D+g5uL(Et|afLo(7xIN@Z8n^#3#dFz;?T&|g0L9kiYpgfyp?d-gEj6?gFhK#YhvXPM73Y1YrX2WuhPk+tLxqt{677&54#HFunlmq"
            b")wr?2ms%?`Y9FyAV7|$Qpr#UZB^wuXGznIqsHo8I1K88(u=YJunagu#>BS2Qp*7D~erd%F`-Z}YEmdcIE)}(lAUfg3j!H%B^Bdf{"
            b"YML3d!vr%+-{tG&a;(;@v?)(OO>q)bLn3mWuB#hq%}27R^UO+11U#Xm+|W<O^_JgoF-vvVy60nU*+Q`VF7yATx>rQ_c09D)h%pr+"
            b"m4h#y=mM!p)*=dxe7m=@N5Q&vZmSZfMEzFgndUGs!|HNB^GQV5uUi_a2oCZJb<~o@o5Wt&uacz0Y7LQtF~*AG$x6$<U#;w&!z+5A"
            b"2v0)!@lv>>#7XQ#W~+fBtw$|4f&}HNsT9}$Q)I<5-n0ppw3oMHaZLD24LFkpFe{>)a{R;zYan2W05dIV@lu3<R-<86fQ_~E0M8V#"
            b"GT1@^kxVG!CVpM%X{~!%i|eCWEmC(^O*6;@1B89`ThxI6Is`axTUcQ2S8EWpOC~w6a>>M6iH4M0TZ~AiZC98`Qda9)nLW;40p1j|"
            b"m5X{__pv$r#fQlxfS6s*bP3#sk)_gvraAX^jNaF+txd1ih2^u%zI9`KlSf3f;R(3wGBQ#heI-9vb~0}lrIpKBe}|JK))q8dGXZ;k"
            b"B`Ttf2buwE;+hq5tXv=`{5a$wvUXdgWCnJW<FrW6YcsBoY?PVzPMHwQ@I~J73de{l3(@pz*4UP35HPR>8$faxYBi{2VBAbk9cM<_"
            b"-EpC$4dhM)#aF?^o9Hm_E0M;ID=Ig+o>P7@oZ3%n1)~x&r#Hm+#L5I5J~msdg(|UN7cVWhV2NF6hr4pkrBmiu{oYHG^M}(fZ?&B?"
            b"TTA8*00iv2AbqwBhtS;|GrR8-Ijn`@)fk#ri1V)eq;Xy(qA!sU(hrXecT{*g+KW!xUcjQ{4xIms>Yz*KrWSg+IZYdjWB5{Uyt5zV"
            b"Z#<^Rm!t&dDwn57t*MqV&c-|M1uPnLtBU5LjM%RALVTL7uugb7+S6)@P{zSEB`GP9jVzt1W68HP$B^2&4q!60<FZyES7)Am4#ewL"
            b"nWKm{f_h8HPBn!;`}~*b95pEl=CuId?X~)KUbQYC;QBR%0tcxH#ElNw4*mtrP@QCBlAwlcX}MwOHX1ax{FswkB9<<gv74_8LyZq}"
            b"8S&XALk<wA&<Tz&<u|@j;A%nhmxOgUw)RTB2$j=5sPOq3SHD70oIpw(&djMssKhJX<91~$z1^zq>1iOv29r6Df_Pd;gTG$$gOe`j"
            b")1;(5Dmq-!WWOMgBRV_9e&NOf1J@%m;Lg<aEy_cP7m<_6+BROK9NV>?l?U58d&}n>8#A^HgVcEd9Xz<zmH#@$3btA-o^^7}pOm8}"
            b"ZBUmar;JX{mriKmb}p~BGbuJ3F@sI8Y&x~4c|Gs1>XWKH>P%EN=BH6qV2lpO{Tyr3{&YoXH9<MfM^;}!R^_@H%6D8(^qtjckaivV"
            b"QLmuD#GNFgR8hm#%{(=y!e-MyKb`%PE9fZ5#W7M*9d3$muEJKs7Xz3btd1-CvFhZ^*mXoG3u!z#Jmm|C5%BwHmn)gS^z=R~-NcO+"
            b"=N8&WqP{?StCVdg5yREOBw0S+#*|boxV4K(#48j$q<De5n#-JH=C=$MrK*<Vz*0OVwm2EpmxIQHsuxM=XU!cQ@e{}3j#qCaJr=Gl"
            b"1#>yV$ym6+nLhZhU$z4rORV%{KVRqO86cvC=W*@Ijqx5WvF632FQcla2WwZP6-H##sBz_|gwpqOIwt9p@J$=I)zAxhN`F#G6OwB!"
            b"wmJneg$o-OF-vPUd2urQ<w1$X^TZ{5^91SPty4Uy9P7P#?o)UA%~`HBMf~`qXO&jBV5TLW?B}R#z~HUq?R)g`)oX(*jx~F_?kaW1"
            b"W8L;^cYe;AeQu<vUXix}^Hi7XPkLH$RsArBWUMIJ_<_C4H{?j0_O|>rNx8k19@cad;Yp`HtSrPc7e2AJ$%H93eqb!tHSayMe9i>#"
            b"^K5q_P;|-`OdPAt>VTC>i^`kRBkVrl1hvg@rj$%g+SKw=-4X1GIXDoh=j$C`dLh<Abgs_iiY`)+5iEiY1#VC1tyH2`ow8C8n4Mw^"
            b"O3yJMvC+D79nEl4iAe_e{#ce9PjvM-BjPl-t^L$s;w^^u=eLb~cK9&)Rl@K=%Z}(3ZxKJH)UoPqY=+C%z#u>I@xj=hjaf43NoY`B"
            b"tp0<loDYy}gTrl1(!R*a__taW){F47V_@y&WQBItB*&V4bORPWd+SF3`j(A47NH@u#KHVLkRLf$D@3D&sx`uu4bEL--70O;n)gAr"
            b"R8v0Xr}&fMeLo-G-e+N0bTLsCE#BrM7#C8<Z(VK#wAq{VhsOF<?SwNRKY%5L>xb?bn^9JmJ%BCPc}(d_wHh@%-1ve{lW;bVRKcH1"
            b"`?#d`2PB&CK4%vGOr=dtM4eV|<>G@gFydCdxnj_u9VCY+*A%FeLur5P0ZByiKjw_23J&CSHYVXl7l>CD2dsJIS{}v@G@$OMOOpzF"
            b"L9IGB)zGXsX}Guh7XE(v`~J+89aeF@*`&^p9);1!%ZCFl?9C)64pekkex@8<7U|ELrpgUdek9rVeBG&pWEf69>Q0Jcp$5=er8A+)"
            b"+1^!6QGuQR;ww7I`hhC9nog%ZTY&4WuG^t9&H}LLYEu|4d4U?ntG=txcz`U{a_G!AL-)VVfWrBLe|-GXg#<$akfJy_#!Ni0x{Q+@"
            b"R%p1ace$ZTIFuQ=PI7Wdx>(dMnO5P%j60q8#~lQ%y#4PEf_k^pS!(l<^Wfy#HC--d8Qe*`M&;t}SaWi6+>Mear@!Rcs<jg<FWv-s"
            b"t6W*%AUTq3;#^s^(*s<10!_E@{U4{RfJ}8*T3tJf+6(Sjt?^wqzQrOIr-#1ptkTRcF02G(sF50Yc3mFzj|iW2m2otzWl12TH{c1u"
            b"Ts<H+3f#%1Q`3GYHmS@ee=oqYGK0Kyo}jrhn#<b-%d%?FrLc#RQ|-`B$@@8cFnB-7<&Rb?Q&Ch;;;JjB3Od;~Hv(;iY(B~Xj2bXP"
            b"GRp(I&312hnK&oF5az0wyL8@XB?b%{!1HJ%L-dEm|1c)?2V)w9!=y)9b!V?Qznkl}ulni4)RZ`a&j&a)xjg}eW`6#6|L}Le`RrFl"
            b"fcVRxvtS3>c*s@NN$cGfC@RGxp9I;JI<>?y_`+G-Xa`jumGad!SV!i!|M;8#{rA86$KUd#a^~JYj|>bxfC)ayJQ%wFtsT_;YItDq"
            b"+eZV#4@bVs;FlTx-HMUy;K1PhY%()P?On}rv`{RqG!=AC6HCc!lE|HzHtS=+*ggw3s^XVXXECT=kfGR`Z}W{mP5Xu=x$5Ba%zksm"
            b"jlGH8iy_Q6$c<^rr`^^omlr4XFgu-U9K{`?pVDbP)ye%|kZ^Ei<na4W@z(=SvxB(x=feXJ9%b=i@bNeJ_p$!_>A>(;L-_yOr}*b*"
            b"+2Myzvk!hYFfx#djsU8}RX=j=qK>Ubpx~+yMV1SguvoT;1d8}vJc%3oZj@}R6}4{qVGPdHr~<I$H>y(_L&zgS(N3-4AnC|9Rfu;$"
            b"W`a<`Is$~*k1Vs;n6KuWUCZ6j(EUMya!C^*5D;DszvNh`{aq1-8*oW7!R=YAS=ryzXw{?AOAjG-u!G~gkZJH@G;{Cn(@$-R{qFE5"
            b"_WyA9@uPw7?BkciL;o*3csKRU<AM8M4}6t<a`*oX{Lgz3EW?LQ<^mv9=TT8ZFu(v^TF(6ZA^%{;k#mu1!v)f$GUQKvX`@!>J@d=N"
            b"j<r#pWz;S+_rAz}IW(Nb5~}xp_{G52AYQid;O13SsCyl$c4`Y?9Znh6`k^YaHcfpPUu?zA!(gI7+6|>`Y}(~M0cJW?pC(IRwAn9J"
            b"mF+JsymvA#*_MW1?6}wlELUjLA8RxZ<YV<5yG1=2DtKudh%E{76&6tY1@q(&V^HPA?cU0saFT5z^JlQdbh*3#oaB6vvty;}Hr!1l"
            b"Z?95+CO9&l^@DVzNAw0K(2+&gz)|<nx*onn?-xKNAC^5Qb-NZ7#Y(IIA;14V>FPn}aszhL)$+7npu>`6j8m-3J+?fFRFzS~Zgi*q"
            b"Sg302&$ZBeI0E`s<rq5_V*N!h4x<llp1|ryVlZwo_|f)DQ`Rl!x|Z4Xt<t-0+HcLrCZmICxt!I)l9O5XD0Qac3L>4+anAh}q1k1K"
            b"h{*d#{K17Rq5%Kg!v6;*veHu"
        ),
    ),
    "DESIGN_FOUNDATIONS.md": (
        "367228b8aa165f467918ac2f79d3dd52766d82afc0d3d28517b8cd14e5fa2fb4",
        (
            b"c-nnfOK%!k7T)JqTxoVAJL*pNY<d?Z(#%L5O*Gw_UbI>YhKh}X!2+BaOT7TcJPn38wy}+gjbAv94LI=w7Z`p_*S%G>%3tX3+yfY="
            b"Gc85QrRvsspYMDpe-YmslOFG!@EH;RWbod&cpRGc_=DdK9^lEdpK%_a@I;J&KWL19_0`wEh@YoCVc##$ge>N)R?Mwl+vWOivADec"
            b"C<{%woO9}3r(Sh(uVndLedyUMN4O>rO7iN1n@ZuQy}97jl1?onw@usZ{T7?QCxlF-<$fM-aZPPyoZ12;K&-v8ZJ9L@4ZSde0@CgF"
            b"g4MqK)G51%YwDyb+ot_~QKi?Mr7M|AI?Y#V^_=CZ(xoaCWy+MX4L6qg)XAw_hNaupx>Mg*7jgS&k!@lltX5uSvuf)^9aUAO2SeTV"
            b"I&Q)mncg5L>+5Rm+TJ&<?xK_VAY&b<mibk;dciKSWO?((y4jM6BaV*B?>h7QYALNMuSn4s;`-n=u2wtYR1e&nBBaPn-fFjHwrbt<"
            b"ICA7$H3r29fm3hFn^l>(bYt@rIh}z|odT?vl@ggd2s!!It*CsRBDl3J>u>uJRh0u}7M-hx>@L6+wUcrhN!ZA7lJ!mNIwK1W`$HF="
            b"$<8WdQ6Nh@?p6%>lIcr|cW1|HwcXuyr;4{_yJO1zGnfdi5NNgf8IaePmbovUJ`r+%!7e5t2m!Y`$9Anr`ZCwZAav8imZ`RmhfZ_S"
            b"Db)LGPHmq2gO^Bd1{Rc21A}t8jjhM)H6juJgg@Yq&fP8CCx#IfKRtT*ck%F{m<<MSPei8-F%$4apNGQJ!W#-k!ya!`_#+|`4g0-O"
            b"BYgk=N*+nwe~hsI`JC{~%mn;i&qTlwFO0c~5MGXn=OOQGWK4t&->ld0jZcT7{!nnNuPYKAL$Dst1wGS#ulR9p#uyWxpig+9C=&I*"
            b"G{&QbcPbbPgeK?2gfZoL=@0#hN#ER>^pi0mQ1|TbgZmH2XR2#mF{)BkCtYsXPn}J*QFmjTYAuBhkd15ASdr$Tllmx|uVLM{_y6|Y"
            b"*T|XNukjUrBfg=hW!XzOhjB<&OEu)m>0aBbIjXkorHaM5u3(2-dHb1swn6R1)b_!xL@L379<D;&o=Y}#Pze^Cy@Y$vv`;hWL{tT;"
            b"n|qVRacMcPZm69zF>3jCk}x5?#u8XE0TVt?@1x#uUl!A9r_;xyLPNdDql?kP)Cq-#Q}4N@x-90YT$gk7q!zaq4(<8tp*r-gT4|_U"
            b"Tug;t8exjd(l#K>e%}CG0+HPKh3p;^ChVlRUv2Xc4*pr`etVlur*??=^5^Jpw{-4YRd9ei^0Z`k-l>%?q9p4XfRD_Xi1?^3G@)92"
            b"hdyNF7@`7YHD}6nQuzP%gP4gz;=`aX9P;~wZ-!7;m(imi@a}(iLc3kGTE~4qkowgox*o8l(nS;!^=|dVEgh*^nS<&c=bT0ye+Y@R"
            b"LbtMk@}OYr0zk0I{N^UQA0Xv!Bsd8)GOEyP_A#S<z#l@3(@V+v9_6H-0~Qf9ZEo4Sd4lamd^E0u{=SO_<QbAA-!3xNGhoU$d1<Zy"
            b"Wn?lT>(^u~CR^&*Ubv*vsqSHTAiD?`YVql#z61)W#w^Bt!o2z>fp*!%0evR-Q@C#*mt<kj-NhJ8Q=u1*QDJI*2@nfdMH^w3-~zV@"
            b"iUv;WHpVc}(plW_dkSpz(tUO0G|nLf$#Z%uviz29f*mv@mUEa<(p;4Xuc_kB-dg68JX^&mL-)wNk8lQaR=$bLM#o7XLx|Pd#NYwS"
            b"(w)KJ<q!Keb7sF+w4%PWrYRdO<jCD9Vmk1!;rkSbL0E@1i-M&_M_=loa0#QjWVSq-J3X!LChp(HY{Vd}4Wre30{;M62~>HsMSzpY"
            b"wjulgSbF6TPKu!MU-8l(ne_z3OHW|dh}{2!hS5o^&31RUFzTt3kk{A>r@(2P0+U!1*QDG!QjG%I0daOKyKX8^e5QJ0ch>BkIJuw6"
            b"K@J?JvB&_bfA#?rDi8#XmiqZTPkLq<G7)#`Ew`MsTBi($$iiTRo5fq4`PjDG+xVv67`ik2wmy9NPtv@;Bby5_`5!+%`5uURO0Cs<"
            b"ZFM@tc^0?1w`Fo!CK8-HmZ>U5=lqCF)P#(lFEziEp^@2RwScW9r?$-T<A&~+F!MHT45Tnm<gS5S0^HX(fLfV{1C2i99LCj|F1KVJ"
            b"pA-GO%|MxB4;n$q(Hij~h3W<rp~*2L#AK#4LL+1$>n8H(HINCl(V)@tDu)C4cJEig*=LCYKXrd19vB@|&l(-XuedlqJ}&xy;}_=}"
            b"SO#Lm5QdjHbISQ(wXy`7x(%RKmb(CIVzzI(YUu#q0zZ%-8lSlgCvlj)K2z1BO?FK1UKfabIS=Gz;o1uJgb?*?-Uf??{kk{@9>&>z"
            b"&^A1zQoN|+=J2N*uiH28D7YG%<VB8XycR_=b-bw7bojJFc7|SRXV_;hb`pP59iC<9jG=|jg*@d;+d`CIPiX#0m0irS^Ehw|vTvGU"
            b"5GBwf7^-NTY_8~yB0e17e2tu0soUlC!MrXrf8bBZUQJ&>Pc3t~&t1|<nSRfOqZKk9!dCY%4Q+_D%x)9do*v5AS*>BiX;4(HURA{#"
            b"R33LriVj*fg%pU-00>sAgXMG+GW(7(oE2(o7!oLTx^y9xxdrshguxRGA5PdK46sx>YMzOIef|hBP#+bPuA^b72&}p#b#<j#PfSby"
            b"LmQ8f4nj6fYN%Q-5=a&87*}U}aNn=@xtwk)DB>y4-Odq!YK{Px3hI}aE%K)x!~Vn-K%oF_Ig7cm0)jx~u-voSd;R4?(^LY+1n66{"
            b"zd~YmmV2~d>HUvles>E(d)wufOne+-&F#R_gO39GY<wK!BN~c=c#r?}89=hZ(+mcVVmu*ZB0<|74?v(zyTB_S#ITv8m>BVT0-tZq"
            b"da2{>SSHRa^F1{TDAP{*H_ekFf{Z`iLwV3)CuN^@x#_5`PvOxOA24F5{Hi&mfX52+L3jO9?KXy!g(ot7vW18((<j|)RZUXGuAj@B"
            b"Gr}G%pIEIf#la`@ypl6655^6W#AH&_CB2FE)9J>FL^2A8NEPq=)V^Ax)vKU@_`eLen+f0cmcX}p1%(j!Lm02yc1Wk)$_`7gb6e_S"
            b"aWuNTLVXtA?2%ec1Hqhbmpg~3%R3X1K@DJ(=><kR#TyVP`D%~iT>b#$05z7)EDZT<PlF%qqAc(9kt2I#ue2owcW;})gAIp)5U4p~"
            b"S|fd)@yj`i!IDwV!)@qp7M)T7wgI0Q@@Neoh`Qyj!}7f2?&FXMhN4&^XXeE4iU`jJqyA~EkkcXW3*qxbJ!7{!ttW^tJmeI%(NGv}"
            b"`HYF#Nxl#YM2IhiM%dIXLz*@`L6E2~T0m6Hi}f^2N_n#lg@qqNLz7|8%oLVlUa~{Mz?|@U!ePG=7NO^&FZBMs-vQxJOQZ"
        ),
    ),
    "DESIGN_COMPONENTS.md": (
        "a21fa27faddb9db96192d78d7bac7bd580da660856cf3cdceacd823b0426d22d",
        (
            b"c-nnfO;aLS7Tx!+$cWi?b@Y6!W;Ze2i;3t(&vZx3qN5`^#VjS-0te9UniZ%BC|@OhfZzv~C{mJWi6tfiKc@4&%v|+fm~-Dv5UY&Y"
            b"RHaGgd-t7t?z!jYAGB|bIX&=Nn>C`rxzJ}Xw6DUi^kC?(;~Tj1(+{|Q5eUCp42O(R?8TQ~{_#ichj~3R`{PgAzl^1*q3Iz_UtElY"
            b"myKBs|IIE1V!?1oo4lj_GH-;mU`*2&B8EQuT8rwjVDx3sh-$HU<1<Z*82?!cM)3BGF|RKN!x1bwtLcG&5se0Cf(yaeYpfQEMf5=I"
            b"i)Ul{(_>7cm~}gC`#vM{=XU>tIL$fRO{dz!eW$-hcM2O`d<8c}p==LIzr|NX%5w5o;?5KgD<YW|=~KDemgSDK@j=EDzr_=XQCwM~"
            b")0634aepHUSN!hp4^^jbdbPORy%HyfGLv&VU0KeH{E?_0i><7iT@}^t?+;nKmvdJK*wm}vdIu+VuOzMywZDJ&ohJA9MBj2QFKsI;"
            b"8hhf%a_Vu89ih?ASnP0<&mof6w)IXP--(BU-OIamENnT}nK1V$mhB_kI(Oc6_+hVp?^I1bG>3ruBK?6EbVo(JF84mz{kP6>g7$h2"
            b"**{MqJ1B`vPMC*YC20>v1nd49FAoTCJVap+u)~!o=A84Z-yaI{pdqay5TtP8+qe+PglqQ3&=az;@Xw%!EFX)jHF`h+jd#7hu6uWY"
            b"3sGBl&$noiaX!3l)2Wv6lY4#!s2GMxUKw=C>)m@<%lKKhN?yP0ny2phnn+g&*Fr~T$G>i6olIKRF2%zRRsdR}&~nWyG1y@gnH<2F"
            b"5_y)ucCu5zPspN-pNqnoSg+W<xZNMf-IT1q1yN+Njl>EwD|fn+7^Y#K4eATwxu+E+vX)4%%R<pPwdllk6CvZmtv5w(M?Bm+tvv$Z"
            b";7~T}0K*+7#l{70io#nQLi;wnh&qe_n(xDUG{y{~?3^Xs#J;n3#!0mMeX&tTkgj=w^UCy{Sif=FyI?S9mRHAlWySR3`!Zb=8%Ls$"
            b"^Ul&hfRUtVRD80&&iu0b4R>_t^xNWAaao0n06;NW9m!r&R<7i2!f9?&c9M7CfEUlm%?nw>yLpa^s~3kEBmdq@rI>77dz`^%k$kEH"
            b"&UK$daQa6`jxYxTr81_Tti{DCQr97FzANJ=V&8hw9o~a?^uTe-J0X_grZDeufuqP05UL?f^guS_ZJFYF#j(yQDGAdVT!4oByzK9b"
            b"ji%haN3GIvH=20St6Rb<5bvrc*5?CpcmP}EuD!|yKj|w;F)t5mK$o^w+xht^=Yc&x$<>A}oYtDSE>P+0j5r3npR-2?&Q1l#bcaJg"
            b"=*8oZJD@8@Nsxk%^DLHAmCtl{&T|YW)j9MvQxXsHX_AV<uKbWzMSkP$wQ=!vG(c54+7{JA6fHfxa?dzX1#V?!t%U$ZyUg)Yj!)N|"
            b";yNN?=4t;nW;AA_+(yABG_0xdPP`2X-!z!eq|CiEH{A9aipbq;Km$noii9D*GFHqi!^lwE!vmQ!#r=l~Vm|52j7T;aH_D^hni_#x"
            b"iiO?VFCxn*TiZG%*~^e7O=t62g#Yr0uzx}YDKuGbY@k+wm2=(~$p&-{bqj5E1}36*SF^Ixp)*0kR047HdwoXp-$C%TCJ{z03S@~|"
            b"Dq7G9nSeq=I7Q(NDvS<NOapN`X)%x5<!un~L}X~E2a7sK^~xR;co#fiKa|lfnUD-V*T_Weu%>LkRR~i}BTC99zlJV^ekGEtPWKq`"
            b"xv3V@N}TSx=PMwtSMU3o@cEs1R0gI0Ec?^QMvb{wpO_Tv<yQ-Y)x71_itY}KSbRvgdo2-vAm*O#<EA@G$^I!JJu1_a>6FZ!FhkM2"
            b"<-v$`m2gS5-BsYS!C^y1af<P2_tj~wExC&fW&k!rrA74FU|5@A!h8C^1?G*w&okj)H6#YDac*wG&}Nomv2X|*KE9H?aTD9q5&5r!"
            b"1<}c4RqoYnIo!J&cW}v%d8MJuH;BwC32+Qbk$S?~<~%Y;{}13#l$Kv%DSK8<Cv6<1>a>U6+q^s`$m#68w#=qbt<;Cl$SkNnuiQ@&"
            b"F~q?rehZ9%2H=jH>VjQpi;y+eSan`fc=R!6r$H;L27+V)VPehBh!>ft3@Iu<qgo1aM9Bi@7DXtJieo^UZmvjt27`9s3rf@ylRoX8"
            b"`lVMXqClt(-XBqiJgA^a%5)1(66GfMj^)jcJ8VKInF`ONI_<W&8qx>ie3KzkZzYJ2#WS{1&V_}a2wP_8;98V&_>=2~qTRV7P1{n^"
            b"*SSZ2KPnxr0B|2}l7HgrMy-hSJBAm)Dq1n=m~P5!QBds3NJ_IAs0FE@l4;6G@eP(#Smxy@F1vlz0#MsYsy%<5j>z4R;+2QUKQ2fJ"
            b"&^Fcc#B`iBUGbY<W^?irbeiOLSQQ(`?qI;y<f)0pzz|+|ss-FanWT2FPf~qZr+;DEYM0dNS+kW#pib_a(JXnF#y;cWcU`nl)%gJr"
            b"p<5k-T)aLS4)t4e<n5W0=FH835JMAAkrihR#w)(>VHc~2Ihhz>L$R87Qgbu!5tYd9l3*uNY{;h1`!XDP_4Kgru!P>h6-G%$w>_?V"
            b"tt=m(OM$pEN{aeBI(wnxv#AGXaiNSXb#tyr^+3z*^p&4$5COI;Zl}Y;2x&>~m|Dl>8AlGoN48Jx0*L&Fvng^P?LCwc;;~02a2S^_"
            b"gz(z!HfSVa{<1N>d(Q`9wR_S?^_c#V)~EN7BeERzCe+3EeVuhyBQnvaU3HNi8y{bO2%P*DteLVar2fn(PA=+<SEl+yDHm%__r&R!"
            b"V9n^x!78es1%Oz=gyge8R%=I)VSgf2?w*s2({ba$;!b4%k;eKYf$$ouO}UyB>$gutBBsZTr>FfIPXD!r5j^rD775PH88k!d(bu8C"
            b"d?XwSFGVp!t5Mwebuk>pxUFl8MkHVam-QL670l{$5scWM<Al*AHEn;cVfcQj2N#wihNgDp(S9)!r0ZCiCU$LcL5~sLzW5}#>8=2|"
            b"QSHZXxNqa~sKEmoDnOexUg}E=7*G=PG_c_Rm*K!t6#p+$OvWs(qQ-&|h^b42I2(*o*!0&z7#%b;M~`saxH2LU#LjXAa-!Ek5lP`x"
            b"_d}g>UXWh^PGrWc-&1quYLlFSQc9A{#0fY_&GxP%hHFqNDrYq^gP9ofKt(5iMOCR*7L7Nslgfm4(Ny8zsHop7Pc$`a(MN*o6;jz&"
            b"R&M+AxLa?~h^Q8ySPI67tl3R-@-4xi-<1o46$fqn&l~0;eY#Mb8IQ-0oB@&;<fFmmkBIXvelQ}-hDJz-V(_CrQ=;n2OE5&))fIL0"
            b"KqMTEYKEd(bZK!h96?49>2lEch5jJMj0vGdga0+Oz=9r)e(`(|Qv^}wi0ue}s8FVydUGj9Muet&>dGVxod-AFdK`ndvXe24Dhyq4"
            b"uS*%bTE(nA`6y#skh-qC#X4#B3XlZK|8`&WR;lw`$EnoRoW{N%jf*EGYEzhJG54q`#2LUV-;PbNMRBT;n~e@xZKyI##`OxXMqY&d"
            b"t$6|sgTe9=w_?~rb91eClX0C#3!H+_KAk#aIXG*C0v{#rQ(oa<Xe&fKTCR>7gYWcbNA(rRw$??dWm{GM<A{%GflWG>mjC$*XDF0q"
            b"wToBme%!t%@wbPYu(l{DOlqL6+aXs)DH-=)vW+kXs#vh>KfY3<{o`jUziYAZD}%yyGqG8IGwk#+Suv5v1wn%ch1R#cWRAWkm~|IN"
            b"R3BLQS5$^Os^D;ZEbrt%`Ecs1e#xrri%OGi1^3VKz^cBD98^d!)Wdu}(&l!?w(|7lLERY-Jc$W2W$(Q_Dv?`N>ds$b<VIZ9I^4#I"
            b"0B0+}j7LGtGWe68RGHze`EwmtFy<XF`J=?bB9j>b+xJeOH`+h{Mxx|wUvpSAHH|7>ij;x74@X0bmJ$=Goj@ROH{H&TkGpcIaJb(D"
            b"=jLOC$&`Beij`8}=Tgv4GA8On))-a)8_s9{1EZ=5&j"
        ),
    ),
}


@lru_cache(maxsize=None)
def legacy_template(name: str) -> bytes:
    """读取固定真实历史夹具并核对摘要；当前规则继续仅以 Skill 为权威。"""
    if name == "UPSTREAM.md":
        return LEGACY_UPSTREAM
    if name == "STANDARDS.md":
        return LEGACY_INDEX
    fingerprint, encoded = LEGACY_INPUTS[name]
    body = zlib.decompress(base64.b85decode(encoded))
    if hashlib.sha256(body).hexdigest() != fingerprint:
        raise AssertionError(f"historical migration fixture fingerprint mismatch: {name}")
    return body


def rendered_legacy(name: str, project: Path, pack: Path) -> bytes:
    from lib.standards_baseline import _observed_baseline
    discovered = validate_with_profile(pack / "project.yaml", project, pack / "roles")
    assert not discovered.errors and discovered.profile is not None, discovered.errors
    values = {
        "PROJECT_NAME": "MyProject", "DOC_PROJECT": "docs/PROJECT.md", "DOC_FEATURES_DIR": "docs/features",
        "DOC_DESIGN_DIR": "docs/standards", "OBSERVED_BASELINE": _observed_baseline(discovered.profile),
        "ENGINEERING_STANDARDS_INDEX": "- [General engineering rules](standards/GENERAL.md)\n- [Upstream and second-development boundaries](standards/UPSTREAM.md)",
        "DESIGN_STANDARDS_INDEX": "- No design standards are configured for the discovered project profile.",
    }
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda match: values[match[1]], legacy_template(name).decode()).encode()


class GeneralOwnershipTest(unittest.TestCase):
    def test_exact_historical_chinese_item_only_is_removed(self):
        from lib.standards_baseline import RULE_ITEM_RE, _without_builtin_items
        source = legacy_template("GENERAL.md")
        old = next(m.group().rstrip(b"\r\n") for m in RULE_ITEM_RE.finditer(source)
                   if m[1] == b"eng-common-005")
        current = (PACK / "platforms/shared/skills/xy-code-standards/references/rules.md").read_bytes()
        paragraphs = {m[1]: m.group().replace(b"\r\n", b"\n").rstrip(b"\n")
                      for m in RULE_ITEM_RE.finditer(current)}
        prefix = "# 项目规范\r\n- Domain: engineering\r\n\r\n".encode()
        note = "\r\n\r\n## 项目备注\r\n必须保留中文及尾部空格  ".encode()
        self.assertEqual(prefix + note, _without_builtin_items(prefix + old + note, paragraphs))
        # 同一条完整历史规则后追加续段或无缩进表格，整个条目便不再属于历史默认值。
        # 这两个负控防止按 ID、首句或段落前缀放宽删除，必须逐字保留用户扩展。
        for extension in (b"\n\n  User continuation must survive.\n",
                          b"\n\n| User table | Contract |\n| --- | --- |\n| Keep | all bytes |\n"):
            with self.subTest(extension=extension):
                body = prefix + old + extension + note
                self.assertEqual(body, _without_builtin_items(body, paragraphs))

    def test_malformed_markers_are_rejected(self):
        valid = COMMON_BEGIN + b"\nold\n" + COMMON_END
        self.assertEqual((0, len(valid)), common_span(valid))
        self.assertIsNone(common_span(b"# Project rules\n"))
        for damaged in (COMMON_BEGIN, COMMON_END, valid + COMMON_BEGIN,
                        COMMON_END + b"\n" + COMMON_BEGIN, b"inline " + valid):
            with self.subTest(damaged=damaged), self.assertRaisesRegex(ValueError, "markers"):
                common_span(damaged)


class GeneralPublisherTest(host_cases.UnifiedHostFixture, unittest.TestCase):
    def fixture(self):
        temporary, project, pack = self.make_fixture()
        self.addCleanup(temporary.cleanup)
        (project / "go.mod").write_text("module example.test/general\n", encoding="utf-8")
        return project, pack

    def publish(self, project, pack, host="shared", *, success=True):
        result = (self.run_script(project, "scripts/scaffold_project_docs.sh") if host == "shared"
                  else host_cases.UnifiedSetupContractTest.run_antigravity_applier(self, project, pack))
        self.assertEqual(0 if success else 1, 0 if result.returncode == 0 else 1,
                         result.stdout + result.stderr)
        return result

    def old_documents(self, project, pack):
        root = project / "docs/standards"
        root.mkdir(parents=True, exist_ok=True)
        for name in ("GENERAL.md", "UPSTREAM.md", "DESIGN_FOUNDATIONS.md", "DESIGN_COMPONENTS.md"):
            (root / name).write_bytes(rendered_legacy(name, project, pack))
        (project / "docs/STANDARDS.md").write_bytes(rendered_legacy("STANDARDS.md", project, pack))

    def test_new_install_creates_no_generic_leaves_or_empty_index(self):
        for host in ("shared", "antigravity"):
            with self.subTest(host=host):
                project, pack = self.fixture()
                self.publish(project, pack, host)
                self.assertFalse((project / "docs/STANDARDS.md").exists())
                self.assertFalse((project / "docs/standards").exists())
                self.assertTrue((project / "docs/PROJECT.md").is_file())
                self.assertEqual([], validate_documents(pack / "project.yaml", project))

    def test_exact_old_default_is_removed_by_both_publishers_and_not_recreated(self):
        for host in ("shared", "antigravity"):
            with self.subTest(host=host):
                project, pack = self.fixture()
                target = project / "docs/standards/UPSTREAM.md"
                target.parent.mkdir(parents=True)
                target.write_bytes(rendered_legacy("UPSTREAM.md", project, pack))
                index = project / "docs/STANDARDS.md"
                index.write_bytes(rendered_legacy("STANDARDS.md", project, pack))
                self.publish(project, pack, host)
                self.assertFalse(target.exists())
                self.assertFalse(index.exists())
                if host == "antigravity":
                    # 测试辅助器的 staging 是本夹具独占过程产物；只清理它，原项目与
                    # 已发布原生资源继续原地复用，才能验证真正的再次安装幂等。
                    shutil.rmtree(project / "antigravity-test-staging")
                before = {p: (p.read_bytes(), p.stat().st_ino) for p in (project / "docs").rglob("*") if p.is_file()}
                self.publish(project, pack, host)
                self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_ino) for p in before})

    def test_common_region_removal_preserves_exact_project_bytes_and_mode(self):
        for host in ("shared", "antigravity"):
            with self.subTest(host=host):
                project, pack = self.fixture()
                target = project / "docs/standards/GENERAL.md"
                target.parent.mkdir(parents=True)
                prefix = "# 专有约束\r\n- Domain: engineering\r\n\r\n".encode()
                suffix = "\r\n\r\n- `[eng-project-only] [hard]` 项目约束。  ".encode()
                target.write_bytes(prefix + common_block(legacy_template("GENERAL.md")) + suffix)
                target.chmod(0o600)
                self.publish(project, pack, host)
                self.assertEqual(prefix + suffix, target.read_bytes())
                self.assertEqual(0o600, stat.S_IMODE(target.stat().st_mode))
                self.assertIn(b"standards/GENERAL.md", (project / "docs/STANDARDS.md").read_bytes())
                self.assertEqual([], validate_documents(pack / "project.yaml", project))

    def test_unmarked_project_file_is_preserved_and_index_only_gains_missing_link(self):
        project, pack = self.fixture()
        general = project / "docs/standards/GENERAL.md"
        general.parent.mkdir(parents=True)
        original = b"# Project General\n- Domain: engineering\n- `[eng-local-only] [hard]` Project rule.\n"
        general.write_bytes(original)
        index = project / "docs/STANDARDS.md"
        before = b"# Custom index\r\n\r\nProject index text.\r\n"
        index.write_bytes(before)
        self.publish(project, pack)
        self.assertEqual(original, general.read_bytes())
        self.assertTrue(index.read_bytes().startswith(before))
        self.assertEqual(1, index.read_bytes().count(b"standards/GENERAL.md"))

    def test_known_default_rule_paragraphs_move_but_project_notes_survive(self):
        from lib.standards_baseline import RULE_ITEM_RE
        for host in ("shared", "antigravity"):
            with self.subTest(host=host):
                project, pack = self.fixture()
                target = project / "docs/standards/GENERAL.md"
                target.parent.mkdir(parents=True)
                old = legacy_template("GENERAL.md")
                secret = next(m.group().rstrip(b"\r\n") for m in RULE_ITEM_RE.finditer(old) if m[1] == b"eng-common-005")
                prefix = b"# Project notes\r\n- Domain: engineering\r\n\r\n"
                note = "\r\n\r\n## 项目备注\r\n保留项目说明及尾部 空格  ".encode()
                target.write_bytes(prefix + secret.replace(b"\n", b"\r\n") + note)
                self.publish(project, pack, host)
                self.assertEqual(prefix + note, target.read_bytes())
                self.assertFalse((project / "docs/STANDARDS.md").exists())

    def test_modified_builtin_id_or_unknown_common_rule_stops_before_writes(self):
        from lib.standards_baseline import RULE_ITEM_RE
        source = (PACK / "platforms/shared/skills/xy-code-standards/references/rules.md").read_bytes()
        secret = next(m.group().rstrip(b"\r\n") for m in RULE_ITEM_RE.finditer(source)
                      if m[1] == b"eng-secrets-001")
        # 与正例使用同一真实旧中文条目；追加内容必须留在原文件并由重复 ID 校验拒绝。
        historical = next(m.group().rstrip(b"\r\n") for m in RULE_ITEM_RE.finditer(legacy_template("GENERAL.md"))
                          if m[1] == b"eng-common-005")
        common = common_block(legacy_template("GENERAL.md"))
        modified = re.sub(rb"(?m)^- `\[eng-common-005\] \[hard\]`[^\r\n]*",
                          b"- `[eng-common-005] [hard]` USER-MODIFIED-CONTRACT", common, count=1)
        extended = tuple(common.replace(COMMON_END, addition + COMMON_END) for addition in (
            b"\nUSER-PLAIN-CONTRACT\n", b"\n  USER-CONTINUATION\n",
            b"\n| USER-TABLE | project contract |\n| --- | --- |\n| Keep | this value |\n",
        ))
        common_prefix = b"# Project rules\n- Domain: engineering\n"
        for variant, body in enumerate((
            b"# Custom General\n- Domain: engineering\n- `[eng-secrets-001] [hard]` Custom meaning must survive.\n",
            b"# General\n- Domain: engineering\n" + COMMON_BEGIN + b"\n- `[eng-project-private] [hard]` Keep me.\n" + COMMON_END,
            COMMON_BEGIN,
            b"# Project rule\n- Domain: engineering\n\n" + secret
            + b"\n\n  Project-specific continuation must retain its rule identity.\n",
            common_prefix + historical + b"\n\n  Historical rule with user continuation must survive.\n",
            common_prefix + historical + b"\n\n| User table | Contract |\n| --- | --- |\n| Keep | all bytes |\n",
            *(common_prefix + region for region in (modified, *extended)),
        )):
            with self.subTest(variant=variant):
                project, pack = self.fixture()
                general = project / "docs/standards/GENERAL.md"
                general.parent.mkdir(parents=True)
                general.write_bytes(body)
                self.publish(project, pack, success=False)
                self.assertEqual(body, general.read_bytes())
                self.assertFalse((project / "docs/PROJECT.md").exists())
                self.assertFalse((project / "docs/STANDARDS.md").exists())

    def test_custom_design_rule_survives_generic_paragraph_migration(self):
        project, pack = self.fixture()
        target = project / "docs/standards/DESIGN_FOUNDATIONS.md"
        target.parent.mkdir(parents=True)
        custom = "\n- `[des-project-brand] [hard]` 品牌映射遵循项目专用源。\n".encode()
        target.write_bytes(rendered_legacy(target.name, project, pack) + custom)
        self.publish(project, pack)
        self.assertTrue(target.read_bytes().endswith(custom))
        ids = re.findall(rb"\[(des-[a-z0-9-]+)\] \[(?:hard|advisory)\]", target.read_bytes())
        self.assertEqual([b"des-project-brand"], ids)
        self.assertEqual([], validate_documents(pack / "project.yaml", project))

    def test_same_size_concurrent_project_edit_is_not_overwritten(self):
        project, pack = self.fixture()
        target = project / "docs/standards/GENERAL.md"
        target.parent.mkdir(parents=True)
        target.write_bytes(legacy_template("GENERAL.md"))
        size = target.stat().st_size
        with patch.dict(os.environ, {"AGENT_WORKFLOW_PACK_TEST_SCAFFOLD_RACE": "managed:docs/standards/GENERAL.md"}):
            result = self.run_script(project, "scripts/scaffold_project_docs.sh")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("changed during publish", result.stdout + result.stderr)
        self.assertEqual(b"X" * size, target.read_bytes())
        self.assertFalse((project / "docs/PROJECT.md").exists())

    def test_edit_after_planning_cannot_be_rebound_as_the_original_input(self):
        """计划后的新内容不得被快照追认为 before，再被旧 after 覆盖。"""
        project, pack = self.fixture()
        target = project / "docs/standards/UPSTREAM.md"
        target.parent.mkdir(parents=True)
        target.write_bytes(legacy_template("UPSTREAM.md"))
        planner = install_workflow.plan_standard_updates
        concurrent = b"# Project-specific replacement\n"

        def change_after_plan(*args, **kwargs):
            result = planner(*args, **kwargs)
            target.write_bytes(concurrent)
            return result

        with patch.object(install_workflow, "plan_standard_updates", side_effect=change_after_plan):
            with self.assertRaisesRegex(install_workflow.InstallError, "迁移规划后发生变更"):
                install_workflow._standard_update_snapshots(pack, project)
        self.assertEqual(concurrent, target.read_bytes())
        self.assertFalse((project / "docs/PROJECT.md").exists())

    def test_antigravity_rollback_restores_deleted_defaults_with_original_mode(self):
        project, pack = self.fixture()
        self.old_documents(project, pack)
        general = project / "docs/standards/GENERAL.md"
        general.chmod(0o640)
        before = {p: (p.read_bytes(), stat.S_IMODE(p.stat().st_mode)) for p in (project / "docs").rglob("*.md")}
        with patch.dict(os.environ, {"AGENT_WORKFLOW_PACK_TEST_FAILPOINT": "antigravity-after-agents-publish"}):
            self.publish(project, pack, "antigravity", success=False)
        self.assertEqual(before, {p: (p.read_bytes(), stat.S_IMODE(p.stat().st_mode)) for p in before})

    def test_antigravity_failure_removes_only_the_created_project_index(self):
        """由真实规划器标记新建薄索引，并在宿主失败后安全撤回，避免只测手工标记。"""
        project, pack = self.fixture()
        leaf = project / "docs/standards/LOCAL.md"
        leaf.parent.mkdir(parents=True)
        original = b"# Local project rules\n- Domain: engineering\n- `[eng-project-local] [hard]` Keep project constraint.\n"
        leaf.write_bytes(original)
        with patch.dict(os.environ, {"AGENT_WORKFLOW_PACK_TEST_FAILPOINT": "antigravity-after-agents-publish"}):
            self.publish(project, pack, "antigravity", success=False)
        self.assertEqual(original, leaf.read_bytes())
        self.assertFalse((project / "docs/STANDARDS.md").exists())


class GeneralAtomicPublicationTest(unittest.TestCase):
    @staticmethod
    def applier():
        # 发布器也是直接脚本入口，按它实际使用的 lib 搜索路径加载，不修改全局环境。
        with patch.object(sys, "path", [str(PACK / "lib"), *sys.path]):
            return importlib.import_module("apply_antigravity_setup")

    def test_antigravity_document_publication_and_rollback_preserve_concurrent_content(self):
        applier = self.applier()
        for moment in ("gap", "after"):
            with self.subTest(moment=moment), tempfile.TemporaryDirectory() as raw:
                project = Path(raw).resolve()
                target = project / "GENERAL.md"
                target.write_bytes(b"original project rules\n")
                change = applier.FileChange(target, b"new common rules\n", 0o600, applier._fingerprint(target))
                plan = applier.Plan(PACK, project, project, "general-publication-test")
                plan.doc_changes.append(change)
                concurrent = b"concurrent project-specific note\n"
                replace = os.replace

                def publish_gap(source, destination):
                    replace(source, destination)
                    if Path(source) == target:
                        target.write_bytes(concurrent)

                if moment == "gap":
                    with patch.object(applier.os, "replace", side_effect=publish_gap):
                        with self.assertRaisesRegex(applier.ApplyError, "cannot atomically replace"):
                            applier._publish_file(change, plan)
                else:
                    applier._publish_file(change, plan)
                    target.write_bytes(concurrent)
                with self.assertRaisesRegex(applier.ApplyError, "Document.*preserved current file and backup"):
                    applier._rollback(plan)
                self.assertEqual(concurrent, target.read_bytes())
                self.assertEqual(b"original project rules\n", change.backup.read_bytes())

    def test_antigravity_keeps_late_modified_document_backup(self):
        applier = self.applier()
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            target = project / "GENERAL.md"
            target.write_bytes(b"original project rules\n")
            change = applier.FileChange(target, b"new common rules\n", 0o600, applier._fingerprint(target))
            plan = applier.Plan(PACK, project, project, "general-backup-test")
            plan.doc_changes.append(change)
            applier._publish_file(change, plan)
            # 模拟编辑器仍持有原 inode，在文件已移入事务备份后继续保存专项。
            change.backup.write_bytes(b"late project-specific change\n")
            with self.assertRaisesRegex(applier.ApplyError, "preserve changed document backup"):
                applier._cleanup_committed(plan)
            self.assertEqual(b"late project-specific change\n", change.backup.read_bytes())
            self.assertEqual(change.body, target.read_bytes())

    def test_deleted_document_restore_preserves_recreation_after_missing_sample(self):
        applier = self.applier()
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            target = project / "GENERAL.md"
            target.write_bytes(b"original default\n")
            change = applier.FileChange(target, None, 0o600, applier._fingerprint(target))
            plan = applier.Plan(PACK, project, project, "restore-missing-race")
            plan.doc_changes.append(change)
            applier._publish_file(change, plan)
            check = applier._assert_unchanged
            concurrent = b"USER-RECREATED-AFTER-SAMPLE\n"
            injected = False

            def inject_after_missing_sample(path, expected):
                nonlocal injected
                check(path, expected)
                if Path(path) == change.backup and not injected:
                    injected = True
                    target.write_bytes(concurrent)

            with patch.object(applier, "_assert_unchanged", side_effect=inject_after_missing_sample):
                with self.assertRaises(applier.ApplyError):
                    applier._rollback(plan)
            self.assertTrue(injected)
            self.assertEqual(concurrent, target.read_bytes())
            self.assertEqual(b"original default\n", change.backup.read_bytes())

    def test_created_index_rollback_preserves_replacement_after_sampling(self):
        applier = self.applier()
        published = b"# Published project standards index\n"
        for replacement in (None, b"USER-REPLACED-INDEX\n", published):
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as raw:
                project = Path(raw).resolve()
                target = project / "STANDARDS.md"
                change = applier.FileChange(target, published, 0o600, applier._fingerprint(target), created_standard_index=True)
                plan = applier.Plan(PACK, project, project, "remove-created-race")
                plan.doc_changes.append(change)
                applier._publish_file(change, plan)
                if replacement is None:
                    applier._rollback(plan)
                    self.assertFalse(target.exists())
                    continue
                read = applier._read_regular
                injected = False

                def inject_after_sampling(path, label):
                    nonlocal injected
                    body = read(path, label)
                    if Path(path) == target and not injected:
                        injected = True
                        candidate = project / "user-index-replacement"
                        candidate.write_bytes(replacement)
                        candidate.chmod(0o600)
                        os.replace(candidate, target)
                    return body

                with patch.object(applier, "_read_regular", side_effect=inject_after_sampling):
                    with self.assertRaises(applier.ApplyError):
                        applier._rollback(plan)
                self.assertTrue(injected)
                self.assertEqual(replacement, target.read_bytes())



class GeneralDeletionTransactionTest(unittest.TestCase):
    def test_deletion_rollback_restores_original_and_preserves_concurrent_recreation(self):
        applier = GeneralAtomicPublicationTest.applier()
        for concurrent in (False, True):
            with self.subTest(concurrent=concurrent), tempfile.TemporaryDirectory() as raw:
                project = Path(raw).resolve()
                target = project / "GENERAL.md"
                target.write_bytes(b"original managed default\n")
                target.chmod(0o640)
                change = applier.FileChange(target, None, 0o640, applier._fingerprint(target))
                plan = applier.Plan(PACK, project, project, "deletion-test")
                plan.doc_changes.append(change)
                applier._publish_file(change, plan)
                self.assertFalse(target.exists())
                if concurrent:
                    target.write_bytes(b"concurrent project rule\n")
                    with self.assertRaisesRegex(applier.ApplyError, "changed after deletion"):
                        applier._rollback(plan)
                    self.assertEqual(b"concurrent project rule\n", target.read_bytes())
                    self.assertEqual(b"original managed default\n", change.backup.read_bytes())
                else:
                    applier._rollback(plan)
                    self.assertEqual(b"original managed default\n", target.read_bytes())
                    self.assertEqual(0o640, stat.S_IMODE(target.stat().st_mode))


class GeneralInstallerRecoveryTest(unittest.TestCase):
    def test_real_three_host_install_then_migration_preserves_business_and_project_rules(self):
        with tempfile.TemporaryDirectory(prefix="workflow-builtin-install-") as raw:
            root = Path(raw).resolve()
            project = root / "中文 Project"
            project.mkdir()
            business = project / "go.mod"
            business.write_bytes(b"module example.test/general\n")
            def install():
                result = subprocess.run(["bash", str(PACK / "install.sh"), str(project)], cwd=root,
                                        text=True, capture_output=True, check=False, timeout=180)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                for host in ("Claude", "Codex", "Antigravity"):
                    self.assertIn(f"{host} --check", result.stdout)
            install()
            self.assertFalse((project / "docs/STANDARDS.md").exists())
            general = project / "docs/standards/GENERAL.md"
            general.parent.mkdir(parents=True)
            prefix = b"# Project rules\n- Domain: engineering\n"
            suffix = "\n- `[eng-project-only] [hard]` 保留本项目特有约束。\n".encode()
            general.write_bytes(prefix + common_block(legacy_template("GENERAL.md")) + suffix)
            general.chmod(0o600)
            index = project / "docs/STANDARDS.md"
            index_before = b"# Custom index\n\nProject explanation.\n"
            index.write_bytes(index_before)
            protected = {p: (p.read_bytes(), p.stat().st_ino) for p in (business, project / "docs/PROJECT.md")}
            config = (project / ".agent-workflow/project.yaml").read_bytes()
            install()
            self.assertEqual(prefix + suffix, general.read_bytes())
            self.assertEqual(0o600, stat.S_IMODE(general.stat().st_mode))
            self.assertTrue(index.read_bytes().startswith(index_before))
            self.assertEqual(config, (project / ".agent-workflow/project.yaml").read_bytes())
            self.assertEqual(protected, {p: (p.read_bytes(), p.stat().st_ino) for p in protected})

    def test_recovery_handles_deletion_and_refuses_concurrent_permission_change(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw).resolve() / "GENERAL.md"
            install_workflow._restore_standard_updates([(path, b"previous rules\n", None, 0o600)])
            self.assertEqual(b"previous rules\n", path.read_bytes())
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            path.write_bytes(b"published rules\n")
            path.chmod(0o640)
            with self.assertRaisesRegex(install_workflow.InstallError, "发生其他变更"):
                install_workflow._restore_standard_updates([(path, b"previous rules\n", b"published rules\n", 0o600)])
            self.assertEqual(b"published rules\n", path.read_bytes())
            self.assertEqual(0o640, stat.S_IMODE(path.stat().st_mode))

    def test_deleted_snapshot_restore_preserves_recreation_after_missing_read(self):
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw).resolve() / "GENERAL.md"
            read = install_workflow.read_file
            concurrent = b"USER-RECREATED-AFTER-READ\n"
            injected = False

            def inject_after_missing_read(path):
                nonlocal injected
                body = read(path)
                if Path(path) == target and body is None and not injected:
                    injected = True
                    target.write_bytes(concurrent)
                return body

            with patch.object(install_workflow, "read_file", side_effect=inject_after_missing_read):
                with self.assertRaises(install_workflow.InstallError):
                    install_workflow._restore_standard_updates([(target, b"old default\n", None, 0o600)])
            self.assertTrue(injected)
            self.assertEqual(concurrent, target.read_bytes())

    def test_created_index_snapshot_rollback_preserves_replacement_after_sampling(self):
        published = b"# Published project standards index\n"
        for replacement in (None, b"USER-REPLACED-INDEX\n", published):
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as raw:
                project = Path(raw).resolve()
                target = project / "STANDARDS.md"
                target.write_bytes(published)
                target.chmod(0o600)
                if replacement is None:
                    install_workflow._restore_standard_updates([(target, None, published, 0o600)])
                    self.assertFalse(target.exists())
                    continue
                read = install_workflow.read_file
                injected = False

                def inject_after_sampling(path):
                    nonlocal injected
                    body = read(path)
                    if Path(path) == target and not injected:
                        injected = True
                        candidate = project / "user-index-replacement"
                        candidate.write_bytes(replacement)
                        candidate.chmod(0o600)
                        os.replace(candidate, target)
                    return body

                with patch.object(install_workflow, "read_file", side_effect=inject_after_sampling):
                    with self.assertRaises(install_workflow.InstallError):
                        install_workflow._restore_standard_updates([(target, None, published, 0o600)])
                self.assertTrue(injected)
                self.assertEqual(replacement, target.read_bytes())

    def test_failed_upgrade_restores_deleted_default_and_index_before_old_setup(self):
        for concurrent in (False, True):
            with self.subTest(concurrent=concurrent), tempfile.TemporaryDirectory() as raw:
                project = Path(raw).resolve() / "project"
                project.mkdir()
                with patch.object(install_workflow, "_run_setup"):
                    install_workflow._install(project, PACK)
                general = project / "docs/standards/UPSTREAM.md"
                general.parent.mkdir(parents=True)
                original = legacy_template("UPSTREAM.md")
                general.write_bytes(original)
                general.chmod(0o600)
                index = project / "docs/STANDARDS.md"
                index_original = legacy_template("STANDARDS.md")
                index.write_bytes(index_original)
                calls = []
                def setup(runtime, target, *options):
                    calls.append(options)
                    if len(calls) == 2:
                        for path, _before, after, _mode in install_workflow._standard_update_snapshots(runtime, target):
                            if after is None:
                                path.unlink()
                            else:
                                path.write_bytes(after)
                        if concurrent:
                            general.write_bytes(b"concurrent project rule\n")
                        raise subprocess.CalledProcessError(7, "setup_all.sh")
                    if len(calls) >= 3:
                        self.assertEqual(original, general.read_bytes())
                        self.assertEqual(index_original, index.read_bytes())
                with patch.object(install_workflow, "_run_setup", side_effect=setup):
                    with self.assertRaises(install_workflow.InstallError):
                        install_workflow._install(project, PACK)
                self.assertEqual(b"concurrent project rule\n" if concurrent else original, general.read_bytes())
                self.assertEqual(index_original, index.read_bytes())
                self.assertEqual(2 if concurrent else 4, len(calls))


if __name__ == "__main__":
    unittest.main()
