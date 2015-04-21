package main

import (
	"bytes"
	"github.com/chihaya/bencode"
	"github.com/labstack/echo"
	"log"
	"net/http"
)

type ScrapeRequest struct {
	InfoHashes []string
}

type ScrapeResponse struct {
	Files []bencode.Dict
}

// Route handler for the /scrape requests
// /scrape?info_hash=f%5bs%de06%19%d3ET%cc%81%bd%e5%0dZ%84%7f%f3%da
func HandleScrape(c *echo.Context) {
	counter <- EV_SCRAPE
	r := getRedisConnection()
	defer returnRedisConnection(r)
	if r.Err() != nil {
		CaptureMessage(r.Err().Error())
		log.Println("Scrape cannot connect to redis", r.Err().Error())
		oops(c, MSG_GENERIC_ERROR)
		counter <- EV_SCRAPE_FAIL
		return
	}

	passkey := c.Param("passkey")

	user := GetUser(r, passkey)
	if user == nil {
		log.Println("Invalid passkey supplied:", passkey)
		oops(c, MSG_GENERIC_ERROR)
		counter <- EV_INVALID_PASSKEY
		return
	}

	q, err := QueryStringParser(c.Request.RequestURI)
	if err != nil {
		CaptureMessage(err.Error())
		log.Println("Failed to parse scrape qs:", err)
		oops(c, MSG_GENERIC_ERROR)
		counter <- EV_SCRAPE_FAIL
		return
	}

	// Todo limit scrape to N torrents
	resp := make(bencode.Dict, len(q.InfoHashes))

	for _, info_hash := range q.InfoHashes {
		torrent := mika.GetTorrentByInfoHash(r, info_hash)
		if torrent != nil {
			resp[info_hash] = bencode.Dict{
				"complete":   torrent.Seeders,
				"downloaded": torrent.Snatches,
				"incomplete": torrent.Leechers,
			}
		} else {
			Debug("Unknown hash:", info_hash)
		}
	}

	var out_bytes bytes.Buffer
	encoder := bencode.NewEncoder(&out_bytes)
	err = encoder.Encode(resp)
	if err != nil {
		CaptureMessage(err.Error())
		log.Println("Failed to encode scrape response:", err)
		oops(c, MSG_GENERIC_ERROR)
		counter <- EV_SCRAPE_FAIL
		return
	}
	encoded := out_bytes.String()
	Debug(encoded)
	c.String(http.StatusOK, encoded)
}
