#!/usr/bin/env python3
"""Authenticate both test extensions over SIP; reject a wrong password."""
import hashlib
import re
import secrets
import socket
import sys
from pathlib import Path

host, config = sys.argv[1:]
accounts = re.findall(r'username = (\d+)\npassword = (\w+)', Path(config).read_text())
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.connect((host, 5060))
sock.settimeout(3)
local_ip, local_port = sock.getsockname()

def register(user, password, good=True):
    call_id = secrets.token_hex(12)
    tag = secrets.token_hex(6)
    uri = f'sip:{host}'
    def request(seq, auth=''):
        message = (f'REGISTER {uri} SIP/2.0\r\n'
                   f'Via: SIP/2.0/UDP {local_ip}:{local_port};branch=z9hG4bK{secrets.token_hex(8)};rport\r\n'
                   f'From: <sip:{user}@{host}>;tag={tag}\r\n'
                   f'To: <sip:{user}@{host}>\r\n'
                   f'Call-ID: {call_id}\r\nCSeq: {seq} REGISTER\r\n'
                   f'Contact: <sip:{user}@{local_ip}:{local_port}>\r\n'
                   f'Expires: 120\r\nMax-Forwards: 70\r\n{auth}Content-Length: 0\r\n\r\n')
        sock.send(message.encode())
        while True:
            response = sock.recv(65535).decode()
            if f'Call-ID: {call_id}' in response and f'CSeq: {seq} REGISTER' in response:
                return response
    challenge = request(1)
    assert challenge.startswith('SIP/2.0 401'), challenge
    params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    realm, nonce = params['realm'], params['nonce']
    md5 = lambda value: hashlib.md5(value.encode()).hexdigest()
    ha1 = md5(f'{user}:{realm}:{password}')
    ha2 = md5(f'REGISTER:{uri}')
    qop = 'auth' if 'auth' in params.get('qop', '').split(',') else None
    cnonce = secrets.token_hex(8)
    response = md5(f'{ha1}:{nonce}:00000001:{cnonce}:auth:{ha2}') if qop else md5(f'{ha1}:{nonce}:{ha2}')
    auth = f'Authorization: Digest username="{user}", realm="{realm}", nonce="{nonce}", uri="{uri}", response="{response}", algorithm=MD5'
    if qop:
        auth += f', qop=auth, nc=00000001, cnonce="{cnonce}"'
    if 'opaque' in params:
        auth += f', opaque="{params["opaque"]}"'
    result = request(2, auth+'\r\n')
    assert result.startswith('SIP/2.0 200' if good else 'SIP/2.0 401'), result
    print(f'PASS: {user}: '+('authenticated registration' if good else 'wrong password rejected'))

assert len(accounts) == 2, 'Expected two disposable test accounts'
for user, password in accounts:
    register(user, password)
register(accounts[0][0], 'incorrect-password', False)

# Exercise the actual SIP/SDP/RTP path, not just configuration parsing.
import struct
import time

user, password = accounts[0]
call_id, tag = secrets.token_hex(12), secrets.token_hex(6)
uri = f'sip:6000@{host}'
rtp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
rtp.bind((local_ip, 0))
rtp_port = rtp.getsockname()[1]
sdp = (f'v=0\r\no=test 1 1 IN IP4 {local_ip}\r\ns=Echo test\r\n'
       f'c=IN IP4 {local_ip}\r\nt=0 0\r\nm=audio {rtp_port} RTP/AVP 0 101\r\n'
       'a=rtpmap:0 PCMU/8000\r\na=rtpmap:101 telephone-event/8000\r\n'
       'a=fmtp:101 0-16\r\na=sendrecv\r\n')

def invite(seq, authorization=''):
    message = (f'INVITE {uri} SIP/2.0\r\n'
               f'Via: SIP/2.0/UDP {local_ip}:{local_port};branch=z9hG4bK{secrets.token_hex(8)};rport\r\n'
               f'From: <sip:{user}@{host}>;tag={tag}\r\nTo: <{uri}>\r\n'
               f'Call-ID: {call_id}\r\nCSeq: {seq} INVITE\r\n'
               f'Contact: <sip:{user}@{local_ip}:{local_port}>\r\nMax-Forwards: 70\r\n'
               f'{authorization}Content-Type: application/sdp\r\nContent-Length: {len(sdp)}\r\n\r\n{sdp}')
    sock.send(message.encode())
    while True:
        response = sock.recv(65535).decode()
        if f'Call-ID: {call_id}' in response and f'CSeq: {seq} INVITE' in response and not response.startswith('SIP/2.0 1'):
            return response

challenge = invite(1)
assert challenge.startswith('SIP/2.0 401'), challenge
ack_headers = [re.search(r'^'+key+r': (.+)', challenge, re.M).group(0).strip() for key in ('Via', 'From', 'To', 'Call-ID')]
sock.send((f'ACK {uri} SIP/2.0\r\n'+'\r\n'.join(ack_headers)+'\r\nCSeq: 1 ACK\r\nContent-Length: 0\r\n\r\n').encode())
params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
realm, nonce = params['realm'], params['nonce']
md5 = lambda value: hashlib.md5(value.encode()).hexdigest()
ha1, ha2 = md5(f'{user}:{realm}:{password}'), md5(f'INVITE:{uri}')
cnonce = secrets.token_hex(8)
response = md5(f'{ha1}:{nonce}:00000001:{cnonce}:auth:{ha2}')
auth = (f'Authorization: Digest username="{user}", realm="{realm}", nonce="{nonce}", '
        f'uri="{uri}", response="{response}", algorithm=MD5, qop=auth, '
        f'nc=00000001, cnonce="{cnonce}"\r\n')
if 'opaque' in params:
    auth = auth.rstrip('\r\n')+f', opaque="{params["opaque"]}"\r\n'
answer = invite(2, auth)
assert answer.startswith('SIP/2.0 200'), answer
to = re.search(r'^To: (.+)', answer, re.M).group(1).strip()
contact = re.search(r'^Contact: <([^>]+)>', answer, re.M).group(1)

def in_dialog(method, seq):
    sock.send((f'{method} {contact} SIP/2.0\r\n'
               f'Via: SIP/2.0/UDP {local_ip}:{local_port};branch=z9hG4bK{secrets.token_hex(8)}\r\n'
               f'From: <sip:{user}@{host}>;tag={tag}\r\nTo: {to}\r\n'
               f'Call-ID: {call_id}\r\nCSeq: {seq} {method}\r\n'
               'Max-Forwards: 70\r\nContent-Length: 0\r\n\r\n').encode())

in_dialog('ACK', 2)
media_ip = re.search(r'c=IN IP4 ([^\r\n]+)', answer).group(1)
media_port = int(re.search(r'm=audio (\d+)', answer).group(1))
rtp.settimeout(0.02)
payload = bytes([0x7e, 0xfe])*80
received = 0
for sequence in range(60):
    packet = struct.pack('!BBHII', 0x80, 0, sequence, sequence*160, 12345)+payload
    rtp.sendto(packet, (media_ip, media_port))
    try:
        echoed, _ = rtp.recvfrom(2048)
        if echoed[12:] == payload:
            received += 1
    except socket.timeout:
        pass
    time.sleep(0.02)
in_dialog('BYE', 3)
rtp.close()
sock.close()
assert received >= 5, f'Expected echoed PCMU audio; received {received} matching packets'
print(f'PASS: authenticated echo call and PCMU RTP round trip ({received} packets)')
