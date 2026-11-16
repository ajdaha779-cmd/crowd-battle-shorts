"""Зоны головы MakeHuman (индексы вершин базового меша hm08) для бороды, усов, щетины и «ёжика».

    python3 tools/make_regions.py <base.obj> engine/regions.json

Координаты base.obj — дециметры, Y вверх, лицо к +Z. Зоны подобраны по ориентирам joint-mouth/eye/jaw."""
import json
import sys

import numpy as np



def regions(V):
    x,y,z=V[:,0],V[:,1],V[:,2]; ax=np.abs(x)
    head=y>5.7
    lips=(ax<0.36)&(y>6.58)&(y<6.84)&(z>1.2)
    chin_neck=(y>5.85)&(y<6.62)&(z>0.15)
    cheek=(ax>0.28)&(y<np.minimum(6.66+0.95*(ax-0.28),7.12))&(y>6.1)&(z>0.0)&(z<1.62)
    beard=head&(chin_neck|cheek)&~lips&(ax<0.68)
    mus=(ax<0.40)&(y>6.83)&(y<6.95)&(z>1.3)
    corners=(ax>0.30)&(ax<0.42)&(y>6.6)&(y<6.9)&(z>1.1)
    stub=beard|mus|corners
    scalp=head&(((y>7.62)&((z<1.05)|(y>7.95)))|((z<-0.35)&(y>6.6))|((ax>0.62)&(y>7.25)&(z<0.75)))
    return {"beard":beard|corners,"mustache":mus|corners,"stubble":stub,"scalp":scalp}


if __name__ == "__main__":
    V = []
    for line in open(sys.argv[1]):
        if line.startswith("v "):
            V.append([float(t) for t in line.split()[1:4]])
    V = np.array(V)[:13380]                       # только тело, без вспомогательной геометрии
    R = regions(V)
    json.dump({k: np.flatnonzero(v).tolist() for k, v in R.items()}, open(sys.argv[2], "w"))
    print({k: int(v.sum()) for k, v in R.items()})
