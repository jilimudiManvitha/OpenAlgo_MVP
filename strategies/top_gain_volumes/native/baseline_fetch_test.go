package main

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"
)

type measuredTransport struct {
	mu                   sync.Mutex
	active, peak, closed int
	starts               []time.Time
}
type countedBody struct {
	io.Reader
	close func()
}

func (b countedBody) Close() error { b.close(); return nil }
func (m *measuredTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	m.mu.Lock()
	m.active++
	if m.active > m.peak {
		m.peak = m.active
	}
	m.starts = append(m.starts, time.Now())
	m.mu.Unlock()
	time.Sleep(40 * time.Millisecond)
	m.mu.Lock()
	m.active--
	m.mu.Unlock()
	body := countedBody{strings.NewReader(`{"s":"ok","candles":[[1,2,3,1,2,100]]}`), func() { m.mu.Lock(); m.closed++; m.mu.Unlock() }}
	return &http.Response{StatusCode: 200, Body: body, Header: make(http.Header)}, nil
}

func TestBoundedWorkersCloseBodiesAndEmitEachSymbol(t *testing.T) {
	transport := &measuredTransport{}
	var output bytes.Buffer
	request := Request{Authorization: "fixture", Symbols: []string{"A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"}}
	started := time.Now()
	fetch(request, &http.Client{Transport: transport}, &output, 5*time.Millisecond)
	elapsed := time.Since(started)
	if transport.peak > 3 || transport.peak < 2 || transport.closed != 12 {
		t.Fatalf("peak=%d bodies closed=%d", transport.peak, transport.closed)
	}
	decoder := json.NewDecoder(&output)
	seen := map[string]bool{}
	for decoder.More() {
		var r Response
		if err := decoder.Decode(&r); err != nil {
			t.Fatal(err)
		}
		if seen[r.Symbol] || r.Code != 200 || len(r.Candles) != 1 {
			t.Fatalf("bad response: %+v", r)
		}
		seen[r.Symbol] = true
	}
	if len(seen) != 12 {
		t.Fatal("missing responses")
	}
	t.Logf("synthetic 12 x 40ms responses: concurrent=%s, sequential latency floor=480ms, peak=%d", elapsed, transport.peak)
}
