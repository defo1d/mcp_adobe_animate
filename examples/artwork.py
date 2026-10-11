"""Original vector artwork for a disposable Flash-style classroom test.

Writes only into this task's asset folder. No downloads, runtime dependencies,
credentials, external SVG references, or calls into any application.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'generated_artwork'
ASSETS.mkdir(parents=True, exist_ok=True)

def svg(name, w, h, contents):
    text = f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">{contents}</svg>'
    (ASSETS / (name + '.svg')).write_text(text, encoding='utf-8')
    return contents

background = '''
<rect width="1280" height="720" fill="#d7d0ba"/>
<path d="M0 420H1280V720H0Z" fill="#a9a896"/>
<path d="M0 420H1280M0 429H1280" fill="none" stroke="#777c73" stroke-width="4"/>
<path d="M0 624H1280V720H0Z" fill="#777c72"/>
<path d="M0 650H1280M170 624L90 720M580 624L570 720M1030 624L1090 720" stroke="#60675f" fill="none" stroke-width="3"/>
<g stroke="#292d2c" stroke-width="5" stroke-linejoin="round">
<path d="M297 69L1110 77L1103 336L289 330Z" fill="#8c7055"/>
<path d="M309 82L1095 89L1089 319L304 316Z" fill="#3f5c55"/>
<path d="M301 317L1101 323L1098 343L295 335Z" fill="#b09d78"/>
<path d="M60 73L208 78L207 308L53 313Z" fill="#8f8f80"/>
<path d="M71 84L194 87L193 297L67 300Z" fill="#abbfba"/>
<path d="M133 86V299M69 181H194" fill="none" stroke="#d3cbb2" stroke-width="10"/>
<path d="M77 105L118 93M78 118L115 107M145 207L182 194" fill="none" stroke="#c8d5ce" stroke-width="4"/>
<path d="M1152 388L1194 380L1188 448L1154 451Z" fill="#b4ab95"/>
</g>
<g fill="none" stroke="#8f9385" stroke-width="2.5" stroke-linecap="round">
<path d="M241 0L236 32L253 43L240 59L248 90M1176 136L1163 153L1169 172L1155 181L1167 202M224 342L234 359L224 372L237 390"/>
<path d="M17 385H110M1190 300H1265M1108 590H1224M209 570H291"/>
</g>
<g fill="#d4dbcf" font-family="Arial" font-weight="bold">
<text x="528" y="122" font-size="25" transform="rotate(1 528 122)">КОНТРОЛЬНАЯ</text>
<text x="346" y="269" font-size="24" transform="rotate(-3 346 269)">x² + 2x = ?</text>
<text x="960" y="295" font-size="17" transform="rotate(2 960 295)">удачи :)</text>
</g>
<path d="M342 283L545 281M768 279L830 271M784 296L845 288" fill="none" stroke="#80978b" stroke-width="3"/>
<g stroke="#323331" stroke-width="4" fill="#e0d7bb">
<circle cx="1194" cy="119" r="44"/>
<path d="M1194 87V93M1226 119H1220M1194 151V145M1162 119H1168M1194 119V99M1194 119L1211 132" fill="none"/>
</g>
<text x="36" y="694" fill="#cbc7ae" font-family="Arial" font-size="18" font-weight="bold" letter-spacing="3">ПОСЛЕДНЯЯ ПАРТА</text>
'''
svg('classroom',1280,720,background)

def head(which, expression):
    skin = '#dbb18d' if which=='left' else '#d8aa80'
    if which=='left':
        shape='''<path d="M58 80L66 177Q71 221 126 236L165 228L172 190L220 182L197 156L195 82Z" fill="SKIN"/>
<path d="M57 110Q29 102 32 136Q36 157 66 158M189 110Q209 96 219 121Q224 143 205 153" fill="SKIN"/>
<path d="M59 102L29 92L46 73L24 55L66 60L63 25L101 43L113 14L142 36L174 18L181 46L211 44L199 83L186 108L164 74L146 100L127 68L102 99L82 79L76 113Z" fill="#302a29"/>
<path d="M87 57L116 49L126 38M151 51L168 41" stroke="#51423a" fill="none" stroke-width="4"/>
<path d="M44 126L55 135M207 121L199 136M196 153L217 172L185 181" fill="none" stroke-width="3"/>'''
    else:
        shape='''<path d="M51 75L61 184Q86 227 153 233L181 216L181 183L221 171L199 147L202 81Z" fill="SKIN"/>
<path d="M60 110Q30 99 31 134Q37 158 64 153M195 103Q220 93 225 121Q227 143 207 151" fill="SKIN"/>
<path d="M46 104L25 73L52 65L37 43L83 49L92 18L122 45L153 15L161 42L192 27L186 61L217 58L201 98L177 82L163 102L144 76L115 94L101 67L82 96L63 83L64 112Z" fill="#a65536"/>
<path d="M56 62L90 58M119 62L145 48M162 57L180 46" stroke="#c87e50" fill="none" stroke-width="4"/>
<path d="M46 121L55 133M212 116L201 130M200 146L219 169L185 181" fill="none" stroke-width="3"/>'''
    shape=shape.replace('SKIN',skin)
    if expression=='neutral':
        eyes='''<path d="M83 114Q100 101 122 113L118 143Q93 154 82 137Z" fill="#f3f0d8"/>
<path d="M140 109Q163 96 183 108L181 138Q157 148 141 130Z" fill="#f3f0d8"/>
<path d="M84 122L120 122M141 118L183 118" fill="none" stroke-width="4"/>
<ellipse cx="110" cy="134" rx="4" ry="8" fill="#252727"/><ellipse cx="169" cy="130" rx="4" ry="8" fill="#252727"/>
<path d="M83 98L119 99M143 94L181 94M114 196Q137 192 159 195" fill="none" stroke-width="5"/>
<path d="M87 160L104 162M148 154L168 157" stroke="#b48464" fill="none" stroke-width="2"/>'''
    elif expression=='panic':
        eyes='''<path d="M75 108Q96 85 125 103L125 146Q94 168 74 146Z" fill="#f3f0d8"/>
<path d="M139 101Q163 82 188 102L187 145Q159 163 138 140Z" fill="#f3f0d8"/>
<circle cx="112" cy="129" r="4" fill="#252727"/><circle cx="174" cy="125" r="4" fill="#252727"/>
<path d="M78 87L117 79M144 80L184 84" fill="none" stroke-width="5"/>
<path d="M116 190Q137 175 157 189L153 218Q130 225 114 210Z" fill="#332829"/>
<path d="M119 193L153 192L153 201L117 201Z" fill="#f1ead2" stroke-width="2"/>
<path d="M90 170L94 178M163 167L169 174" fill="none" stroke-width="2.5"/>
<path d="M219 71Q228 92 218 95Q207 95 219 71Z" fill="#a9c7c3" stroke-width="2.5"/>'''
    elif expression=='blink':
        eyes='''<path d="M80 132Q101 137 123 129M143 126Q162 131 183 124M83 100L120 100M144 94L183 95M114 196Q137 192 159 195" fill="none" stroke-width="5"/>'''
    else:
        eyes='''<path d="M78 113L124 108L122 145Q94 155 79 138Z" fill="#f3f0d8"/>
<path d="M140 107L186 114L181 143Q154 150 141 132Z" fill="#f3f0d8"/>
<path d="M80 123L123 120M142 117L185 123" fill="none" stroke-width="4"/>
<ellipse cx="114" cy="134" rx="4" ry="7" fill="#252727"/><ellipse cx="173" cy="134" rx="4" ry="7" fill="#252727"/>
<path d="M79 98L123 88M143 87L187 103M112 197L145 199L160 193" fill="none" stroke-width="5"/>'''
    return svg(which+'_'+expression,250,260,'<g stroke="#252727" stroke-width="4.5" stroke-linejoin="round" stroke-linecap="round">'+shape+eyes+'</g>')

heads={}
for who in ('left','right'):
    for expr in ('neutral','panic','sideeye','blink'):heads[(who,expr)]=head(who,expr)

left_body='''<g stroke="#252727" stroke-width="5" stroke-linejoin="round" stroke-linecap="round">
<path d="M122 18L121 57L93 80L133 114L166 92L181 58L160 49L163 15Z" fill="#dbb18d"/>
<path d="M103 61L35 79L12 186L87 199L105 144L100 254L232 254L222 147L263 211L304 184L256 88L181 61L153 103Z" fill="#536c73"/>
<path d="M103 61L127 113L153 103L167 121L181 61M92 115L77 172M213 118L230 175" fill="none" stroke="#34494e" stroke-width="4"/>
<path d="M23 170L89 184L79 215L16 203ZM269 175L300 186L288 218L257 199Z" fill="#dbb18d"/>
<path d="M127 183L186 183M128 190L173 190" fill="none" stroke="#34494e" stroke-width="3"/>
</g>'''
right_body='''<g stroke="#252727" stroke-width="5" stroke-linejoin="round" stroke-linecap="round">
<path d="M122 18L121 59L92 83L143 115L177 66L160 49L163 15Z" fill="#d8aa80"/>
<path d="M113 70L60 81L35 132L16 193L71 211L101 165L93 254L232 254L223 151L266 196L303 173L261 88L177 61L146 103Z" fill="#3b4347"/>
<path d="M117 76L145 103L172 71L190 254L113 254Z" fill="#923e36"/>
<path d="M111 70L106 134L87 120L98 85M180 66L207 110L187 121L195 199" fill="none" stroke="#1f292b" stroke-width="4"/>
<path d="M31 174L78 192L63 222L18 207ZM265 166L299 174L290 209L251 187Z" fill="#d8aa80"/>
<path d="M132 154L163 154M131 163L155 163" fill="none" stroke="#c17257" stroke-width="3"/>
</g>'''
svg('left_body',320,270,left_body);svg('right_body',320,270,right_body)

desk='''<g stroke="#282d2c" stroke-width="5" stroke-linejoin="round">
<path d="M0 34L1280 16L1280 65L0 86Z" fill="#a48c66"/>
<path d="M0 86L1280 65V238H0Z" fill="#7c694f"/>
<path d="M0 90L1280 70" fill="none" stroke="#564e41" stroke-width="8"/>
<path d="M15 105L1264 87M319 94V236M983 81V236" fill="none" stroke="#655740" stroke-width="3"/>
<path d="M259 15L441 11L461 44L268 48Z" fill="#ddd6bd"/>
<path d="M667 10L789 7L810 30L684 37Z" fill="#c4cbb8"/>
<path d="M309 50L313 45L430 41L431 46Z" fill="#984b3d"/>
</g>
<g stroke="#4f493d" fill="none" stroke-width="2.5" stroke-linecap="round">
<path d="M105 132L210 130M118 141L232 137M605 191L687 195M615 202L702 204M1000 120L1081 116"/>
</g>'''
svg('desk',1280,238,desk)
svg('hand',130,100,'''<g stroke="#252727" stroke-width="4" stroke-linejoin="round" stroke-linecap="round">
<path d="M19 49L54 39L63 15Q65 8 72 12L73 37L86 10Q90 4 96 11L92 43L102 23Q107 16 112 24L105 53Q125 54 123 65L103 80L66 89L19 75Z" fill="#d8aa80"/>
<path d="M53 41L65 57M76 42L87 58M102 53L93 68" fill="none" stroke-width="3"/>
<path d="M4 43L26 42L26 83L3 85Z" fill="#3b4347"/>
</g>''')
svg('phone',64,116,'''<g stroke="#252727" stroke-width="4" stroke-linejoin="round">
<path d="M8 4L55 7L58 109L5 113Z" fill="#333b3e"/>
<path d="M13 17L50 19L50 80L12 83Z" fill="#abc4a0" stroke-width="2.5"/>
<path d="M19 25H44M19 34H43M18 47H25M33 47H42M18 58H25M33 58H42M18 70H25M33 70H42" stroke="#586d58" stroke-width="3"/>
<circle cx="31" cy="96" r="5" fill="#8b9790" stroke-width="2"/>
</g>''')
svg('announcement',670,104,'''<path d="M10 16L653 9L660 88L13 97Z" fill="#d8d8c0" stroke="#293a33" stroke-width="4"/>
<text x="335" y="64" text-anchor="middle" fill="#593631" font-family="Arial" font-weight="bold" font-size="43" letter-spacing="2">СДАЁМ ТЕЛЕФОНЫ.</text>''')
svg('boast',290,106,'''<path d="M8 7L276 9L282 72L113 75L72 101L83 75L8 77Z" fill="#ede7cd" stroke="#252727" stroke-width="4" stroke-linejoin="round"/>
<text x="145" y="54" text-anchor="middle" fill="#303a36" font-family="Arial" font-weight="bold" font-size="31">Я ГОТОВ.</text>''')
svg('reply',392,144,'''<path d="M8 8L382 6L383 106L210 108L174 137L177 108L8 109Z" fill="#ede7cd" stroke="#252727" stroke-width="4" stroke-linejoin="round"/>
<text x="196" y="48" text-anchor="middle" fill="#303a36" font-family="Arial" font-weight="bold" font-size="27">ЭТО... КАЛЬКУЛЯТОР.</text>
<text x="196" y="84" text-anchor="middle" fill="#6c594a" font-family="Arial" font-size="21">честно.</text>''')
svg('thud',136,84,'''<path d="M9 33L1 5L37 18L62 1L77 20L122 7L114 37L134 69L100 62L75 80L55 58L16 72Z" fill="#dbc18b" stroke="#292d2c" stroke-width="3"/>
<text x="69" y="52" text-anchor="middle" fill="#743d32" font-family="Arial" font-weight="bold" font-size="33">ТУК!</text>''')

