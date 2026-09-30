// Bounded concurrent FYERS daily-history download. Credentials arrive on stdin.
// At most eight dispatches/second, 120/minute, three in flight, 2 MiB/body.
package main

import (
	"bufio"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"os"
	"sync"
	"time"
)

type Request struct {
	Authorization string   `json:"authorization"`
	Symbols       []string `json:"symbols"`
	From          string   `json:"from"`
	To            string   `json:"to"`
}
type Response struct {
	Symbol  string      `json:"symbol"`
	Candles [][]float64 `json:"candles"`
	Code    int         `json:"code"`
}

func main() {
	var input Request
	if err := json.NewDecoder(io.LimitReader(os.Stdin, 2<<20)).Decode(&input); err != nil || len(input.Symbols) > 5000 {
		os.Exit(2)
	}
	transport := &http.Transport{MaxIdleConns: 4, MaxIdleConnsPerHost: 3, MaxConnsPerHost: 3, IdleConnTimeout: 30 * time.Second, ForceAttemptHTTP2: true}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: 20 * time.Second}
	fetch(input, client, os.Stdout, 125*time.Millisecond)
}

func fetch(input Request, client *http.Client, destination io.Writer, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	jobs := make(chan string)
	var wg sync.WaitGroup
	var output sync.Mutex
	writer := bufio.NewWriter(destination)
	for i := 0; i < 3; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for symbol := range jobs {
				params := url.Values{"symbol": {symbol}, "resolution": {"1D"}, "date_format": {"1"}, "range_from": {input.From}, "range_to": {input.To}, "cont_flag": {"1"}}
				req, _ := http.NewRequest("GET", "https://api-t1.fyers.in/data/history?"+params.Encode(), nil)
				req.Header.Set("Authorization", input.Authorization)
				result := Response{Symbol: symbol, Code: 502}
				response, err := client.Do(req)
				if err == nil {
					var body struct {
						Status  string      `json:"s"`
						Code    int         `json:"code"`
						Candles [][]float64 `json:"candles"`
					}
					decodeErr := json.NewDecoder(io.LimitReader(response.Body, 2<<20)).Decode(&body)
					response.Body.Close()
					result.Code = response.StatusCode
					if decodeErr == nil && response.StatusCode == 200 && (body.Status == "ok" || body.Status == "no_data") {
						result.Candles = body.Candles
						result.Code = 200
					} else if response.StatusCode == 200 {
						result.Code = body.Code
						if result.Code == 0 {
							result.Code = 502
						}
					}
				}
				output.Lock()
				json.NewEncoder(writer).Encode(result)
				writer.Flush()
				output.Unlock()
			}
		}()
	}
	starts := make([]time.Time, 0, 120)
	for _, symbol := range input.Symbols {
		if len(starts) == 120 {
			if delay := time.Until(starts[0].Add(time.Minute)); delay > 0 {
				time.Sleep(delay)
			}
			starts = starts[1:]
		}
		<-ticker.C
		jobs <- symbol
		starts = append(starts, time.Now())
	}
	close(jobs)
	wg.Wait()
}
