% GUI'ye heartbeat paketi gönderir (docs/MIL_PROTOKOL.md). Gerçek MATLAB'da DOĞRULANMADI.
% state: 1 hazır, 2 çalışıyor, 3 duraklatıldı, 4 durdu, 5 hata
function mil_send_heartbeat(u, seq, simTime, state)
    pkt = [typecast(uint16(hex2dec('4543')), 'uint8'), uint8(1), uint8(2), ...
           typecast(uint32(seq), 'uint8'), typecast(double(simTime), 'uint8'), ...
           uint8(state), uint8([0 0 0])];
    write(u, pkt, "uint8", "127.0.0.1", 25001);   % u = udpport("datagram")
end
