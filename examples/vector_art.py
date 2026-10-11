"""Convert this example's original, fixed SVG artwork to closed native primitives.

No user SVGs, external references, scripts or network resources are accepted.
The example uses native Arial text and intentionally omits SVG text rotation.
"""
import re
import xml.etree.ElementTree as ET
from artwork import ASSETS

def commands(d,ox,oy):
    tokens=re.findall(r'[MLHVQCZ]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?',d)
    if re.sub(r'[MLHVQCZ\d.eE,+\-\s]','',d):raise ValueError('Unsupported example path')
    result=[];i=0;x=y=0;op=None
    sizes=dict(M=2,L=2,H=1,V=1,Q=4,C=6,Z=0)
    while i<len(tokens):
        if tokens[i] in sizes:op=tokens[i];i+=1
        if op is None:raise ValueError('Missing path operation')
        if op=='Z':result.append(['Z']);op=None;continue
        n=sizes[op];values=[float(v) for v in tokens[i:i+n]]
        if len(values)!=n:raise ValueError('Incomplete example path')
        i+=n
        if op=='H':x=values[0];result.append(['L',x-ox,y-oy]);continue
        if op=='V':y=values[0];result.append(['L',x-ox,y-oy]);continue
        x,y=values[-2:];result.append([op]+[v-(ox if j%2==0 else oy) for j,v in enumerate(values)])
        if op=='M':op='L'
    return result

def artwork(name,eye_only=False,skin_only=False):
    root=ET.fromstring((ASSETS/(name+'.svg')).read_text());ox=float(root.attrib['width'])/2;oy=float(root.attrib['height'])/2
    output=[]
    def visit(node,inherited):
        style={**inherited,**node.attrib};kind=node.tag.split('}')[-1]
        if kind in ('svg','g'):
            for child in node:visit(child,style)
            return
        color=lambda key:None if style.get(key,'none')=='none' else style[key]
        primitive=dict(fill=color('fill'),stroke=color('stroke'),stroke_width=float(style.get('stroke-width',1)))
        if kind=='path':
            d=style['d']
            if eye_only:
                d=''.join(part for part in re.split(r'(?=M)',d) if part and not part.startswith(('M114 196','M116 190','M119 193','M112 197')))
                if not d:return
            primitive.update(type='path',commands=commands(d,ox,oy))
        elif kind in ('rect','ellipse','circle'):
            if kind=='rect':
                left=float(style.get('x',0));top=float(style.get('y',0));right=left+float(style['width']);bottom=top+float(style['height'])
            else:
                cx=float(style['cx']);cy=float(style['cy']);rx=float(style.get('rx',style.get('r')));ry=float(style.get('ry',style.get('r')))
                left,top,right,bottom=cx-rx,cy-ry,cx+rx,cy+ry
            primitive.update(type='rect' if kind=='rect' else 'ellipse',bounds=dict(left=left-ox,top=top-oy,right=right-ox,bottom=bottom-oy))
        elif kind=='text':
            size=int(style['font-size']);x=float(style['x'])-ox;y=float(style['y'])-oy;content=''.join(node.itertext())
            width=max(size*len(content)*.68,size*2)
            if style.get('text-anchor')=='middle':x-=width/2
            primitive.update(type='text',text=content,font_size=size,bold=style.get('font-weight')=='bold',bounds=dict(left=x,top=y-size*1.1,right=x+width,bottom=y+size*.3))
        else:raise ValueError('Unsupported example SVG element')
        output.append(primitive)
    visit(root,{})
    return output[:5] if skin_only else (output[5:] if eye_only else output)

def mouth_frames():
    def path(c,fill=None,stroke='#252727',width=4):return dict(type='path',commands=c,fill=fill,stroke=stroke,stroke_width=width)
    def ellipse(l,t,r,b,fill):return dict(type='ellipse',bounds=dict(left=l,top=t,right=r,bottom=b),fill=fill,stroke='#252727',stroke_width=3)
    return [
        [path([['M',-11,66],['Q',12,63,34,65]])],
        [ellipse(-9,54,36,83,'#332829'),path([['M',-5,58],['L',32,58],['L',30,66],['L',-4,66],['Z']],'#f1ead2',None)],
        [ellipse(2,54,28,85,'#332829')],
        [path([['M',-12,59],['Q',8,86,36,56],['Q',10,73,-12,59],['Z']],'#332829')],
        [path([['M',-10,57],['L',36,58],['L',34,74],['L',-11,73],['Z']],'#f1ead2'),path([['M',0,59],['L',0,71],['M',13,59],['L',13,72],['M',25,60],['L',25,71]],None,'#998976',1)],
        [ellipse(-7,51,37,91,'#332829'),path([['M',-2,81],['Q',14,71,30,81],['L',29,86],['Q',10,91,-2,81],['Z']],'#b76260',None)]
    ]
