'use strict';
(function () {
    const data = JSON.parse(document.getElementById('manifest').textContent);
    const image = document.getElementById('frame');
    const seek = document.getElementById('seek');
    const button = document.getElementById('play');
    let index = 0;
    let timer = null;
    seek.max = data.frames.length - 1;
    function show() {
        image.src = data.frames[index];
        seek.value = index;
        document.getElementById('position').textContent = 'Frame ' + (data.frame_numbers[index] + 1) + ' · ' + (index + 1) + '/' + data.frames.length;
    }
    function stop() { clearInterval(timer); timer = null; button.textContent = 'Play'; }
    function play() {
        stop(); button.textContent = 'Pause';
        timer = setInterval(function () { index = (index + 1) % data.frames.length; show(); }, 1000 / (data.fps * Number(document.getElementById('speed').value)));
    }
    button.onclick = function () { if (timer) stop(); else play(); };
    document.getElementById('previous').onclick = function () { stop(); index = (index + data.frames.length - 1) % data.frames.length; show(); };
    document.getElementById('next').onclick = function () { stop(); index = (index + 1) % data.frames.length; show(); };
    seek.oninput = function () { stop(); index = Number(seek.value); show(); };
    document.getElementById('speed').onchange = function () { if (timer) play(); };
    show();
}());
