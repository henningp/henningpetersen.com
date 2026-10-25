import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const template = readFileSync(new URL('../infra/redirect/redirect.js.tftpl', import.meta.url), 'utf8');
const code = template.replace('${target_origin}', JSON.stringify('https://henningpetersen.com'));

function redirect(uri = '/', querystring = {}, host = 'henningpetersen.de') {
  return runInNewContext(`${code}\nhandler(event)`, {
    event: { request: { uri, querystring, headers: { host: { value: host } } } },
  });
}

test('redirects apex and www permanently to the fixed HTTPS destination', () => {
  for (const host of ['henningpetersen.de', 'www.henningpetersen.de', 'attacker.example']) {
    const response = redirect('/', {}, host);
    assert.equal(response.statusCode, 301);
    assert.equal(response.headers.location.value, 'https://henningpetersen.com/');
  }
});

test('preserves encoded paths and query parameters without double encoding', () => {
  const response = redirect('/a%20b/photo', {
    'search%20term': { value: 'a%26b+c' },
    empty: { value: '' },
  });
  assert.equal(response.headers.location.value,
    'https://henningpetersen.com/a%20b/photo?search%20term=a%26b+c&empty=');
});

test('preserves every repeated query value without duplicating the first', () => {
  const response = redirect('/photos', {
    tag: { value: 'one', multiValue: [{ value: 'one' }, { value: 'two' }] },
    page: { value: '2' },
  });
  assert.equal(response.headers.location.value,
    'https://henningpetersen.com/photos?tag=one&tag=two&page=2');
});

test('a protocol-relative-looking path cannot replace the target hostname', () => {
  assert.equal(redirect('//attacker.example/path').headers.location.value,
    'https://henningpetersen.com//attacker.example/path');
});
