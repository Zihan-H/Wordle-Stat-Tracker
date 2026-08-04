import discord
from discord import app_commands
from discord import ui
from discord.ext import tasks
import re
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as ticker
import requests
import datetime as dt
import os
import json
import logging
import sys
from flask import Flask
import threading
import time

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True
client = discord.Client(intents = intents)
tree = app_commands.CommandTree(client) 
raw = requests.get('https://engaging-data.com/pages/scripts/wordlebot/wordlepuzzles.js').content[14:] # thanks chris
logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(sys.stdout)])

servers = {}

class WGuild():
    def __init__(self, gid, gname, owner):
        self.gid = gid
        self.gname = gname
        self.owner = owner
        self.BASE_LOSS_WEIGHT = 7.5 # it's what NYT decided to use for broad averages: https://www.nytimes.com/2023/12/17/upshot/wordle-bot-year-in-review.html
        self.server = {}
        self.calendar = {}
        self.par_Q1 = 0
        self.par_Q2 = 0
        self.par_Q3 = 0
        self.par_mean = 0
        self.sglobal = {}
        self.gpar_Q1 = 0
        self.gpar_Q2 = 0
        self.gpar_Q3 = 0
        self.gpar_mean = 0

    def init_sglobal(self):
        data = json.loads(raw)
        currdate = dt.date(2022, 8, 12)
        for day in range(419, int(list(data.keys())[-1])):
            if currdate not in self.sglobal:
                if str(day) in data:
                    wordle = data[str(day)]
                    total = 0
                    for score in range(1, 7):
                        total += score * wordle['individual'][score - 1]
                    total += self.BASE_LOSS_WEIGHT * (100 - wordle['cumulative'][-1])
                    par = total / 100
                    self.sglobal[currdate] = par
                else:
                    self.sglobal[currdate] = None
            currdate += dt.timedelta(days = 1)
        pardata = np.array(list(self.sglobal.values()))
        pardata = pardata[pardata != None]
        self.gpar_Q1 = np.quantile(pardata, 0.25)
        self.gpar_Q2 = np.median(pardata)
        self.gpar_Q3 = np.quantile(pardata, 0.75)
        self.gpar_mean = np.mean(pardata)
        
class Player:
    def __init__(self, pid, pname):
        self.pid = pid
        self.pname = pname
        self.scores = np.resize(np.array([[]]), (0, 3))
        self.crowns = 0
        self.losses = 0
        self.currstreak = 0
        self.maxstreak = 0
        self.numgames = 0

    def __repr__(self):
        return str(self.pname) + str(self.scores)

    def updateScores(self, score, crown, date):
        if len(self.scores[self.scores[:, 2] == date]) == 0:
            if crown:
                self.crowns += 1
            elif score == 'X':
                self.losses += 1
            self.numgames += 1
            self.scores = np.append(self.scores, [[score, crown, date]], axis = 0)
        
    def getGamesPlayed(self):
        return len(self.scores) + self.losses
        
class Day:    
    def __init__(self, date, leaderboard, channel, numPlayers, par, image):
        self.date = date
        wordle = requests.get(f"https://www.nytimes.com/svc/wordle/v2/{date:%Y-%m-%d}.json").json()
        self.word = wordle['solution']
        self.wordlenum = wordle['days_since_launch']
        self.leaderboard = leaderboard
        self.channel = channel
        self.numPlayers = numPlayers
        self.par = par
        self.image = image

    def __repr__(self):
        return self.word + ' ' + str(self.date) + ' ' + str(self.leaderboard)

    def mergeLeaderboard(self, newboard, wguild):
        server = wguild.server
        newsum = self.par * self.numPlayers
        BASE_LOSS_WEIGHT = wguild.BASE_LOSS_WEIGHT
        for row in range(len(newboard[:, 0])):
            i = 0
            last = False
            while newboard[row][0] > self.leaderboard[i][0]:
                if (i + 1) == len(self.leaderboard[:, 0]):
                    last = True
                    break
                i += 1
            if newboard[row][0] != self.leaderboard[i][0]:
                if i == 0:
                    for col in self.leaderboard[0][1:list(self.leaderboard[0]).index('0')]:
                        pid = int(col.strip())
                        player = server[pid]
                        index = list(player.scores[:, 2]).index(self.date)
                        player.scores[index][1] = False
                        player.crowns -= 1
                self.numPlayers += list(newboard[row]).index('0') - 1
                if newboard[row][0] == 'X':
                    newsum += BASE_LOSS_WEIGHT * (list(newboard[row]).index('0') - 1)
                else:
                    newsum += int(newboard[row][0]) * (list(newboard[row]).index('0') - 1)
                if last:
                    i += 1
                self.leaderboard = np.insert(self.leaderboard, i, newboard[row], axis = 0)
            else:
                for col in newboard[row][1:list(newboard[row]).index('0')]:
                    if col not in self.leaderboard[i]:
                        self.numPlayers += 1
                        if newboard[row][0] == 'X':
                            newsum += BASE_LOSS_WEIGHT
                        else:
                            newsum += int(newboard[row][0])
                        self.leaderboard[i][list(self.leaderboard[i]).index('0')] = col
        self.par = newsum / self.numPlayers

def ripScores(raw, date, wguild):
    server = wguild.server
    BASE_LOSS_WEIGHT = wguild.BASE_LOSS_WEIGHT
    scores = np.resize(np.array([[]]), (0, len(server) + 1))
    score = ''
    players = []
    scorers = []
    total = 0
    for line in raw.split('\n'):
        crown = False
        if '@' in line:
            if '👑' in line:
                crown = True
            score = line[line.index('/') - 1]
            for pid in line.split('@')[1:]:
                if '>' in pid:
                    pid = int(pid[:pid.index('>')])
                elif '<' in pid:
                    for i in server:
                        if server[i].pname == pid[:-2]:
                            pid = i
                            break
                else:
                    for i in server:
                        if server[i].pname == pid.strip():
                            pid = i
                            break
                if pid in server:
                    player = server[pid]
                    players += [pid]
                    scorers += [pid]
                    if score != 'X':
                        total += int(score)
                    else:
                        total += BASE_LOSS_WEIGHT
                    player.updateScores(score, crown, date)
            scores = np.append(scores, [[score] + scorers + [0 for i in range(len(server) - len(scorers))]], axis = 0)
            scorers = []
    return (scores, len(players), total)             

async def prep_guild(guild):
    wguild = servers[guild.id]
    server = wguild.server
    calendar = wguild.calendar
    for member in guild.members:
        if not(member.bot):
            server[member.id] = Player(member.id, member.display_name)
    logging.info("server loaded")
    count = 1
    for channel in guild.channels:
        if (type(channel) != discord.channel.CategoryChannel):
            rep = True
            startpoint = dt.datetime.today()
            try:
                messagelist = [m async for m in channel.history(limit = 100, before = startpoint)]
            except(discord.Forbidden, discord.DiscordServerError):
                logging.info("skipping past inaccessible (private/empty) channel")
                continue
            logging.info("new channel" + str(channel))
            while rep:
                for message in messagelist:
                    if (message.author.id == 1211781489931452447) and ('👑' in message.content):
                        logging.info(str(count))
                        count += 1
                        date = message.created_at.date() - dt.timedelta(days = 1)
                        check = calendar.get(date)
                        if check == None:
                            rip = ripScores(message.content, date, wguild)
                            scores = rip[0]
                            numPlayers = rip[1]
                            par = rip[2] / numPlayers
                            calendar[date] = Day(date, scores, channel, numPlayers, par, message.attachments[0].url)
                        elif channel == check.channel:
                            date = message.created_at.date()
                            rip = ripScores(message.content, date, wguild)
                            scores = rip[0]
                            numPlayers = rip[1]
                            par = rip[2] / numPlayers
                            calendar[date] = Day(date, scores, channel, numPlayers, par, message.attachments[0].url)
                        else:
                            newboard = ripScores(message.content, date, wguild)[0]
                            calendar[date].mergeLeaderboard(newboard, wguild)
                if len(messagelist) < 100:
                    rep = False
                else:
                    startpoint = messagelist[-1].created_at
                    messagelist = [m async for m in channel.history(limit = 100, before = startpoint)]
                
    logging.info("messages loaded")
    for pid in server:
        server[pid].scores = server[pid].scores[server[pid].scores[:, 2].argsort()[::-1]]
        streak = 0
        maxstreak = 0
        if len(server[pid].scores) != 0:
            prevdate = server[pid].scores[0][2]
        else:
            continue
        for row in server[pid].scores[server[pid].scores[:, 2].argsort()]:
            if streak == 0:
                streak += 1
            elif row[2] == (prevdate + dt.timedelta(days = 1)):
                streak += 1
            else:
                streak = 1
            if row[0] == 'X':
                streak = 0
            if streak > maxstreak:
                maxstreak = streak
            prevdate = row[2]
        if prevdate + dt.timedelta(days = 1) != dt.date.today():
            streak = 0
        server[pid].currstreak = streak
        server[pid].maxstreak = maxstreak
    if len(calendar) > 0:
        pardata = np.array([calendar[day].par for day in calendar])
        wguild.par_Q1 = np.quantile(pardata, 0.25)
        wguild.par_Q2 = np.median(pardata)
        wguild.par_Q3 = np.quantile(pardata, 0.75)
        wguild.par_mean = np.mean(pardata)
    return

@client.event
async def on_ready():
    await tree.sync()
    print(f'We have logged in as {client.user}')
    for guild in client.guilds:
        wguild = WGuild(guild.id, guild.name, guild.owner)
        servers[guild.id] = wguild
        await prep_guild(guild)
        wguild.init_sglobal()
    return

@client.event
async def on_guild_join(guild):
    servers[guild.id] = WGuild(guild.id, guild.name, guild.owner)
    await prep_guild(guild)
    return

@client.event
async def on_member_join(member):
    wguild = servers[member.guild.id]
    if not (member.id in wguild.server):
        wguild.server[member.id] = Player(member.id, member.nick)
    elif not (member.nick == wguild.server[member.id].pname):
        wguild.server[member.id].pname = member.nick
    return

@client.event
async def on_member_update(before, after):
    wguild = servers[after.guild.id]
    if not (before.nick == after.nick):
        wguild.server[after.id].pname = after.nick
    return

@client.event
async def on_message(message):
    if (message.author.id == 1211781489931452447) & ('👑' in message.content):
        wguild = servers[message.guild.id]
        date = message.created_at.date() - dt.timedelta(days = 1)
        check = calendar.get(date)
        if check == None:
            rip = ripScores(message.content, date, wguild)
            scores = rip[0]
            numPlayers = rip[1]
            par = rip[2] / numPlayers
            calendar[date] = Day(date, scores, message.channel, numPlayers, par, message.attachments[0].url)
        elif message.channel == check.channel:
            date = message.created_at.date()
            rip = ripScores(message.content, date, wguild)
            scores = rip[0]
            numPlayers = rip[1]
            par = rip[2] / numPlayers
            calendar[date] = Day(date, scores, message.channel, numPlayers, par, message.attachments[0].url)
        else:
            newboard = ripScores(message.content, date, wguild)[0]
            calendar[date].mergeLeaderboard(newboard, wguild)
        for pid in wguild.server:
            server[pid].scores = server[pid].scores[server[pid].scores[:, 2].argsort()[::-1]]       
        pardata = np.array([calendar[day].par for day in calendar])
        wguild.par_Q1 = np.quantile(pardata, 0.25)
        wguild.par_Q2 = np.median(pardata)
        wguild.par_Q3 = np.quantile(pardata, 0.75)
        wguild.par_mean = np.mean(pardata)
        if date not in wguild.sglobal:
            raw = requests.get('https://engaging-data.com/pages/scripts/wordlebot/wordlepuzzles.js').content[14:]
            wguild.init_sglobal()
    return

class HistoryView(ui.LayoutView):
    crowncol = "[1;33m"
    goodcol = "[2;32m"
    badcol = "[2;31m"

    box = ui.Container()
    acrow = ui.ActionRow()
    
    def __init__(self, scores, header, emoji, wguild):
        super().__init__()
        self.scores = scores
        self.page = 0
        self.header = header
        self.emoji = emoji
        self.wguild = wguild
        self.numpages = int(np.ceil(len(scores) / 10)) - 1
        if self.numpages < 0:
            self.numpages = 0
        if self.numpages == 0:
            self.acrow.children[2].disabled = True
        self.acrow.children[1].label = f"Page {(self.page + 1)} / {(self.numpages + 1)}"
        self.box.accent_colour = discord.Colour.teal()
        self.box.add_item(ui.TextDisplay(header))
        self.fillbox(self.box, self.page, self.scores, self.emoji, self.wguild)

    @classmethod
    def fillbox(self, box, page, scores, emoji, wguild):
        for i in range(10 * page, min(10 * (page + 1), len(scores))):
            row = scores[i]
            data = "```ansi\n "
            data += "%s: " % str(i + 1).zfill(int(np.log10(len(scores))) + 1)
            day = wguild.calendar[row[2]]
            data += row[2].isoformat()
            data += " |   "
            data += str(day.wordlenum).zfill(4)
            data += "   |  "
            data += day.word.upper()
            data += "  |   "
            if row[1]:
                data += HistoryView.crowncol
            elif row[0] == 'X':
                data += HistoryView.badcol
            elif int(row[0]) <= day.par:
                data += HistoryView.goodcol
            else:
                data += HistoryView.badcol
            data += row[0]
            data += "[0m"
            data += "   | "
            data += "%.3f" % np.round(day.par, decimals = 3)
            data += " | "
            if wguild.sglobal[row[2]] != None:
                data += "%.3f ```" % np.round(wguild.sglobal[row[2]], decimals = 3)
            else:
                data += "UNAVAILABLE"
            box.add_item(ui.TextDisplay(data))
            box.add_item(ui.Separator())

    @acrow.button(label = "Previous", style = discord.ButtonStyle.primary, disabled = True)
    async def prev(self, interaction: discord.Interaction, button: ui.Button):
        self.page -= 1
        self.acrow.children[1].label = f"Page {(self.page + 1)} / {(self.numpages + 1)}"
        self.acrow.children[2].disabled = False
        if self.page == 0:
            self.acrow.children[0].disabled = True
        self.box.clear_items()
        self.clear_items()
        self.box.add_item(ui.TextDisplay(self.header))
        self.fillbox(self.box, self.page, self.scores, self.emoji, self.wguild)
        self.add_item(self.box)
        self.add_item(self.acrow)
        await interaction.response.edit_message(view = self)

    @acrow.button(label = "filler", style = discord.ButtonStyle.secondary, disabled = True)
    async def nothing(self, interaction: discord.Interaction, button: ui.Button):
        return

    @acrow.button(label = "Next", style = discord.ButtonStyle.primary, disabled = False)
    async def next(self, interaction: discord.Interaction, button: ui.Button):
        self.page += 1
        self.acrow.children[1].label = f"Page {(self.page + 1)} / {(self.numpages + 1)}"
        self.acrow.children[0].disabled = False
        if self.page == self.numpages:
            self.acrow.children[2].disabled = True
        self.box.clear_items()
        self.clear_items()
        self.box.add_item(ui.TextDisplay(self.header))
        self.fillbox(self.box, self.page, self.scores, self.emoji, self.wguild)
        self.add_item(self.box)
        self.add_item(self.acrow)
        await interaction.response.edit_message(view = self)
        
class CrownLossView(HistoryView):
    def __init__(self, scores, header, emoji, wguild):
        super().__init__(scores, header, emoji, wguild)
        if emoji == '👑':
            self.box.accent_colour = discord.Colour.gold()
        elif emoji == '❌':
            self.box.accent_colour = discord.Colour.red()

    @classmethod
    def fillbox(self, box, page, scores, emoji, wguild):
        box.add_item(ui.Separator())
        for i in range(10 * page, min(10 * (page + 1), len(scores))):
            row = scores[i]
            data = "``` "
            data += "%s: " % str(i + 1).zfill(int(np.log10(len(scores))) + 1)
            data += emoji + " "
            data += str(row[2]) + " "
            data += wguild.calendar[row[2]].word.upper() + " "
            if wguild.sglobal[row[2]] != None:
                data += "%s/6 (Server Par %.3f | Global Par %.3f)" % (row[0], np.round(wguild.calendar[row[2]].par, decimals = 3), np.round(wguild.sglobal[row[2]], decimals = 3))
            else:
                data += "%s/6 (Server Par %.3f | Global Par UNAVAILABLE)" % (row[0], np.round(wguild.calendar[row[2]].par, decimals = 3))
            data += " ```"
            box.add_item(ui.TextDisplay(data))
            box.add_item(ui.Separator())

@tree.command(name = "history", description = "[player]'s last [x {default: 10}] Wordles since [start: {format: YYYY-MM-DD, default: today}}]")
async def history(interaction: discord.Interaction, player: discord.Member, x: int | None, start: str | None):
    await interaction.response.defer(ephemeral = True, thinking = True)
    wguild = servers[interaction.guild_id]
    server = wguild.server
    calendar = wguild.calendar
    view = ui.LayoutView()
    if x == None:
        x = 10
    if x < 1:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid x"))
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    try:
        start = dt.date.fromisoformat(start)
    except(ValueError, TypeError):
        if start == None:
            start = dt.date.today()
        else:
            box = ui.Container(accent_colour = discord.Colour.magenta())
            box.add_item(ui.TextDisplay("Invalid start date"))
            view.add_item(box)
            await interaction.followup.send(view = view)
            return
    if player.id not in server:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    pid = player.id
    if x == 401:
        x = 70
        pid = 1
    elif x == 402:
        x = 70
        pid = 2
    scores = server[pid].scores[server[pid].scores[:, 2] <= start]
    scores = scores[scores[:, 2].argsort()[::-1]]
    view = HistoryView(scores[:x], "```" + " " * (int(np.log10(len(scores)) + 2)) + "    Date    | Wordle # |  Word   | Score |  Par  |  GPar ```", '', wguild)
    await interaction.followup.send(view = view)
    return

@tree.command(name = "line", description = "Line graph for [player] from [start {default: oldest Wordle}] to [end {default: most recent Wordle}]")
@app_commands.describe(start = "format: YYYY-MM-DD", end = "format: YYYY-MM-DD")
async def line(interaction: discord.Interaction, player: discord.Member, start: str | None, end: str | None):
    await interaction.response.defer(ephemeral = True, thinking = True)
    server = servers[interaction.guild_id].server
    BASE_LOSS_WEIGHT = servers[interaction.guild_id].BASE_LOSS_WEIGHT
    view = ui.LayoutView()
    if player.id not in server:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    try:
        start = dt.date.fromisoformat(start)
    except(ValueError, TypeError):
        if start == None:
            start = dt.date(2000, 1, 1)
        else:
            box = ui.Container(accent_colour = discord.Colour.magenta())
            box.add_item(ui.TextDisplay("Invalid start date"))
            view.add_item(box)
            await interaction.followup.send(view = view)
            return
    try:
        end = dt.date.fromisoformat(end)
    except(ValueError, TypeError):
        if end == None:
            end = dt.date.today()
        else:
            box = ui.Container(accent_colour = discord.Colour.magenta())
            box.add_item(ui.TextDisplay("Invalid end date"))
            view.add_item(box)
            await interaction.followup.send(view = view)
            return
    player = server[player.id]
    data = player.scores[player.scores[:, 2] >= start]
    data = data[data[:, 2] <= end]
    losses = data[data[:, 0] == 'X']
    data = data[data[:, 0] != 'X']
    data[:, 0] = np.array([int(i) for i in data[:, 0]])
    crowns = data[data[:, 1] == True]
    for date in np.arange(data[-1][2], (data[0][2] + dt.timedelta(days = 1))):
        date = date.item()
        for i in range(len(data)):
            if data[i][2] == date:
                break
            elif data[i][2] < date:
                data = np.insert(data, i, np.array([None, None, date]), axis = 0)
                break
    fig = plt.figure(figsize=(max(len(data) * 0.125, 8), 4.8))
    ax = fig.add_subplot()
    ax.plot(data[:, 2], data[:, 0], zorder = 0)
    ax.scatter(crowns[:, 2], crowns[:, 0], marker = '*', c = 'xkcd:gold', s = 100, zorder = 1)
    ax.scatter(losses[:, 2], [BASE_LOSS_WEIGHT for i in losses], marker = 'X', c = 'xkcd:crimson', s = 100, zorder = 2)
    ax.set_yticks(np.array([BASE_LOSS_WEIGHT, 6, 5, 4, 3, 2, 1, 0]), ['X', '6', '5', '4', '3', '2', '1', '0'])
    ax.set_xlabel("Date")
    ax.tick_params(axis = 'x', labelrotation = 90)
    ax.xaxis.set_major_locator(mdates.DayLocator(interval = 7))
    ax.xaxis.set_minor_locator(mdates.DayLocator(interval = 1))
    ax.grid(visible = True, which = 'major', axis = 'x', lw = 2)
    ax.grid(visible = True, which = 'major', axis = 'y', lw = 1)
    ax.grid(visible = True, which = 'minor', axis = 'x', lw = 1)
    ax.set_ylabel("Score")
    ax.set_title(player.pname)
    fig.savefig("%s.png" % str(player.pid), bbox_inches = "tight", dpi = 100)
    await interaction.followup.send(file = discord.File("%s.png" % str(player.pid)))
    os.remove("%s.png" % str(player.pid))
    return

@tree.command(name = "bar", description = "Bar chart for [player] from [start {default: oldest Wordle}] to [end {default: most recent Wordle}]")
@app_commands.describe(start = "format: YYYY-MM-DD", end = "format: YYYY-MM-DD")
async def bar(interaction: discord.Interaction, player: discord.Member, start: str | None, end: str | None):
    await interaction.response.defer(ephemeral = True, thinking = True)
    server = servers[interaction.guild_id].server
    view = ui.LayoutView()
    if player.id not in server:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    try:
        start = dt.date.fromisoformat(start)
    except(ValueError, TypeError):
        if start == None:
            start = dt.date(2000, 1, 1)
        else:
            box = ui.Container(accent_colour = discord.Colour.magenta())
            box.add_item(ui.TextDisplay("Invalid start date"))
            view.add_item(box)
            await interaction.followup.send(view = view)
            return
    try:
        end = dt.date.fromisoformat(end)
    except(ValueError, TypeError):
        if end == None:
            end = dt.date.today()
        else:
            box = ui.Container(accent_colour = discord.Colour.magenta())
            box.add_item(ui.TextDisplay("Invalid end date"))
            view.add_item(box)
            await interaction.followup.send(view = view)
            return
    player = server[player.id]
    data = player.scores[player.scores[:, 2] >= start]
    data = data[data[:, 2] <= end]
    numones = len(data[data[:, 0] == '1'])
    numtwos = len(data[data[:, 0] == '2'])
    numthrees = len(data[data[:, 0] == '3'])
    numfours = len(data[data[:, 0] == '4'])
    numfives = len(data[data[:, 0] == '5'])
    numsixes = len(data[data[:, 0] == '6'])
    fig = plt.figure()
    ax = fig.add_subplot()
    bars = ax.bar(['1', '2', '3', '4', '5', '6', 'X'], [numones, numtwos, numthrees, numfours, numfives, numsixes, player.losses])
    ax.set_xlabel = "Score"
    ax.set_ylabel = "Frequency"
    ax.set_yticks(range(0, max([numones, numtwos, numthrees, numfours, numfives, numsixes, player.losses]) + 1, 1))
    ax.set_title(player.pname)
    ax.yaxis.set_major_locator(ticker.MultipleLocator(10))
    ax.yaxis.set_minor_locator(ticker.MultipleLocator(2))
    ax.grid(visible = True, axis = 'y', which = 'both')
    bars.patches[-1].set(color = "xkcd:crimson")
    fig.savefig("%s.png" % str(player.pid))
    await interaction.followup.send(file = discord.File("%s.png" % str(player.pid)))
    os.remove("%s.png" % str(player.pid))
    return

@tree.command(name = "crowns", description = "Number of times [player] got top score on the Wordle")
async def crowns(interaction: discord.Interaction, player: discord.Member, secret: int | None):
    await interaction.response.defer(ephemeral = True, thinking = True)
    server = servers[interaction.guild_id].server
    calendar = servers[interaction.guild_id].calendar
    if player.id not in server:
        view = ui.LayoutView()
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    pid = player.id
    if secret != None:
        pid = secret
    view = CrownLossView(server[pid].scores[list(server[pid].scores[:, 1])], f"You have won {server[pid].crowns} crowns:", '👑', servers[interaction.guild_id])
    await interaction.followup.send(view = view)
    return

@tree.command(name = "fails", description = "Number of times [player] failed to solve the Wordle")
async def fails(interaction: discord.Interaction, player: discord.Member, secret: int | None):
    await interaction.response.defer(ephemeral = True, thinking = True)
    server = servers[interaction.guild_id].server
    calendar = servers[interaction.guild_id].calendar
    if player.id not in server:
        view = ui.LayoutView()
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    pid = player.id
    if secret != None:
        pid = secret
    view = CrownLossView(server[pid].scores[server[pid].scores[:, 0] == 'X'], f"{player.display_name} has failed to solve {server[pid].losses} Wordles:", '❌', servers[interaction.guild_id])
    await interaction.followup.send(view = view)
    return

@tree.command(name = "solved", description = "Number of times [player] solved the Wordle")
async def solved(interaction: discord.Interaction, player: discord.Member):
    await interaction.response.defer(ephemeral = True, thinking = True)
    server = servers[interaction.guild_id].server
    view = ui.LayoutView()
    if player.id not in server:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    box = ui.Container(ui.TextDisplay(f"{player.display_name} has solved {(server[player.id].numgames - server[player.id].losses)} Wordles"), accent_colour = discord.Colour.brand_green())
    view.add_item(box)
    await interaction.followup.send(view = view)
    return

@tree.command(name = "games_played", description = "Number of times [player] played the Wordle")
async def games_played(interaction: discord.Interaction, player: discord.Member):
    await interaction.response.defer(ephemeral = True, thinking = True)
    server = servers[interaction.guild_id].server
    view = ui.LayoutView()
    if player.id not in server:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    box = ui.Container(ui.TextDisplay(f"{player.display_name} has played {server[player.id].numgames} Wordles"), accent_colour = discord.Colour.purple())
    view.add_item(box)
    await interaction.followup.send(view = view)
    return

@tree.command(name = "crown_rate", description = "% of all played Wordles where [player] won a crown")
async def crown_rate(interaction: discord.Interaction, player: discord.Member):
    await interaction.response.defer(ephemeral = True, thinking = True)
    server = servers[interaction.guild_id].server
    view = ui.LayoutView()
    if player.id not in server:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    box = ui.Container(ui.TextDisplay("%s has earned a crown in %.2f%% Wordles" % (player.display_name, 100 * np.round((server[player.id].crowns / server[player.id].numgames), decimals = 2))), accent_colour = discord.Colour.gold())
    view.add_item(box)
    await interaction.followup.send(view = view)
    return

@tree.command(name = "fail_rate", description = "% of all played Wordles [player] failed to solve")
async def fail_rate(interaction: discord.Interaction, player: discord.Member):
    await interaction.response.defer(ephemeral = True, thinking = True)
    server = servers[interaction.guild_id].server
    view = ui.LayoutView()
    if player.id not in server:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    box = ui.Container(ui.TextDisplay("%s has failed to solve %.2f%% of their Wordles" % (player.display_name, 100 * np.round((server[player.id].losses / server[player.id].numgames), decimals = 2))), accent_colour = discord.Colour.red())
    view.add_item(box)
    await interaction.followup.send(view = view)
    return

@tree.command(name = "average", description = "[player]'s average score over the last [x {default: all solved<OPT: played> Wordles}] Wordles")
@app_commands.describe(losses = "<OPT: if losses = True, includes losses scored with the server's BASE_LOSS_WEIGHT>")
async def average(interaction: discord.Interaction, player: discord.Member, x: int | None, losses: bool | None):
    await interaction.response.defer(ephemeral = True, thinking = True)
    server = servers[interaction.guild_id].server
    BASE_LOSS_WEIGHT = servers[interaction.guild_id].BASE_LOSS_WEIGHT
    view = ui.LayoutView()
    if player.id not in server:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    raw = server[player.id].scores[:, 0]
    scores = []
    if losses == None:
        scores = [int(score) for score in raw[raw != 'X']]
        if len(scores) == 0:
            box = ui.Container(ui.TextDisplay("Go solve more Wordles, buddy"), accent_colour = discord.Colour.red())
            view.add_item(box)
            await interaction.followup.send(view = view)
            return
    else:
        for score in raw:
            if score == 'X':
                scores += [BASE_LOSS_WEIGHT]
            else:
                scores += [int(score)]
    if x == None:
        x = len(scores)
    if x <= 0:
        box = ui.Container(ui.TextDisplay("Invalid x"), accent_colour = discord.Colour.red())
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    average = sum(scores[:x]) / x
    box = ui.Container(ui.TextDisplay("%s has an average Wordle score of %.2f, %s" % (player.display_name, np.round(average, decimals = 2), "excluding losses." if (losses == None) else "including losses as a score of %.2f / 6" % BASE_LOSS_WEIGHT)), accent_colour = discord.Colour.teal())    
    view.add_item(box)
    await interaction.followup.send(view = view)
    return

@tree.command(name = "current_streak", description = "[player]'s current Wordle solving streak")
async def current_streak(interaction: discord.Interaction, player: discord.Member):
    await interaction.response.defer(ephemeral = True, thinking = True)
    server = servers[interaction.guild_id].server
    if player.id not in server:
        view = ui.LayoutView()
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    box = ui.Container(ui.TextDisplay("%s currently has a %i Wordle solving streak" % (player.display_name, server[player.id].currstreak)), accent_colour = discord.Colour.orange())
    view = ui.LayoutView()
    view.add_item(box)
    await interaction.followup.send(view = view)
    return

@tree.command(name = "best_streak", description = "[player]'s all time best Wordle solving streak")
async def best_streak(interaction: discord.Interaction, player: discord.Member):
    await interaction.response.defer(ephemeral = True, thinking = True)
    server = servers[interaction.guild_id].server
    view = ui.LayoutView()
    if player.id not in server:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    box = ui.Container(ui.TextDisplay("%s's all time best Wordle streak %s %i %s long" % (player.display_name, ("is ongoing and currently" if (server[player.id].currstreak == server[player.id].maxstreak) else "was"), server[player.id].maxstreak, ("day" if (server[player.id].maxstreak == 1) else "days"))), accent_colour = discord.Colour.orange())
    view.add_item(box)
    await interaction.followup.send(view = view)
    return

async def local_summary(interaction, date, pars_from_server):
    wguild = servers[interaction.guild_id]
    server = wguild.server
    calendar = wguild.calendar
    BASE_LOSS_WEIGHT = wguild.BASE_LOSS_WEIGHT
    par = 0
    par_Q1 = 0
    par_Q3 = 0
    view = ui.LayoutView()
    try:
        date = dt.date.fromisoformat(date)
    except(ValueError):
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("No recorded Wordle on given date"))
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    day = calendar[date]
    if pars_from_server:
        par = day.par
        par_Q1 = wguild.par_Q1
        par_Q3 = wguild.par_Q3
        par_mean = wguild.par_mean
    else:
        par = wguild.sglobal[date]
        par_Q1 = wguild.gpar_Q1
        par_Q3 = wguild.gpar_Q3
        par_mean = wguild.gpar_mean
    data = date.strftime("%A, %B %d, %Y")
    data += "\nWord: %s" % day.word
    if par != None:
        data += "\nPar %.2f (Difficulty: %s)\n\n👑 " % (np.round(par, decimals = 2), ("Easy" if par <= par_Q1 else "Medium" if par <= par_Q3 else "Hard"))
    else:
        data += "Global par data and difficulty are unavailable for this Wordle, try using server pars"
    for row in day.leaderboard:
        row = np.append(row[np.nonzero(row)], ['0'])
        data +=  row[0] + " / 6:  " 
        for pid in row[1:]:
            pid = int(pid)
            data += server[pid].pname
            total = 0
            for score in server[pid].scores[:, 0]:
                if score == 'X':
                    total += BASE_LOSS_WEIGHT
                else:
                    total += int(score)
            average = total / len(server[pid].scores[:, 0])
            if par != None:
                data += " [Expected: %.2f]" % (average * (par / par_mean))
            if row[list(row).index(str(pid)) + 1] != '0':
                data += ", "
            else:
                break
        data += "\n"
    box = ui.Section(data, accessory = ui.Thumbnail(media = day.image))
    cont = ui.Container(box, accent_colour = discord.Colour.blurple())
    view.add_item(cont)
    await interaction.followup.send(view = view)
    return

@tree.command(name = "summary", description = "Summary info on [date {format: YYYY-MM-DD}]'s Wordle")
@app_commands.describe(pars_from_server = "<OPT: if True, uses server data for pars/difficulty ranking, else uses global data")
async def summary(interaction: discord.Interaction, date: str, pars_from_server: bool | None):
    await interaction.response.defer(ephemeral = True, thinking = True)
    await local_summary(interaction, date, False if pars_from_server == None else pars_from_server)

@tree.command(name = "hardest", description = "Hardest of the last [x {default: all Wordles}] Wordles with [at_least {default: 1}] players")
@app_commands.describe(pars_from_server = "<OPT: if True, uses server data for pars/difficulty ranking, else uses global data")
async def hardest(interaction: discord.Interaction, x: int | None, at_least: int | None, pars_from_server: bool | None):
    await interaction.response.defer(ephemeral = True, thinking = True)
    calendar = servers[interaction.guild_id].calendar
    view = ui.LayoutView()
    if x == None:
        x = len(calendar)
    elif x <= 0:
        box = ui.Container(ui.TextDisplay("Invalid x"), accent_colour = discord.Colour.red())
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    if at_least == None:
        at_least = 1
    elif at_least <= 0:
        box = ui.Container(ui.TextDisplay("Invalid at_least"), accent_colour = discord.Colour.red())
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    if pars_from_server == None:
        pars_from_server = False
    maxpar = -1
    maxdate = None
    wordles = np.array([list(calendar.keys()), list(calendar.values())]).T
    wordles = wordles[wordles[:, 0].argsort()[::-1]]
    for row in wordles[:x]:
        wordle = row[1]
        if wordle.numPlayers >= at_least:
            if wordle.par > maxpar:
                maxdate = wordle.date
                maxpar = wordle.par
    if maxdate == None:
        box = ui.Container(ui.TextDisplay("No Wordle in the server meets the condition of having at least %i players" % at_least), accent_colour = discord.Colour.red())
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    await local_summary(interaction, maxdate.isoformat(), pars_from_server)
    return

@tree.command(name = "easiest", description = "Easiest of the last [x {default: all Wordles}] Wordles with [at_least {default: 1}] players")
@app_commands.describe(pars_from_server = "<OPT: if True, uses server data for pars/difficulty ranking, else uses global data")
async def easiest(interaction: discord.Interaction, x: int | None, at_least: int | None, pars_from_server: bool | None):
    await interaction.response.defer(ephemeral = True, thinking = True)
    calendar = servers[interaction.guild_id].calendar
    view = ui.LayoutView()
    if x == None:
        x = len(calendar)
    elif x <= 0:
        box = ui.Container(ui.TextDisplay("Invalid x"), accent_colour = discord.Colour.red())
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    if at_least == None:
        at_least = 1
    elif at_least <= 0:
        box = ui.Container(ui.TextDisplay("Invalid at_least"), accent_colour = discord.Colour.red())
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    if pars_from_server == None:
        pars_from_server = False
    minpar = 999
    mindate = None
    wordles = np.array([list(calendar.keys()), list(calendar.values())]).T
    wordles = wordles[wordles[:, 0].argsort()[::-1]]
    for row in wordles[:x]:
        wordle = row[1]
        if wordle.numPlayers >= at_least:
            if wordle.par < minpar:
                mindate = wordle.date
                minpar = wordle.par
    if mindate == None:
        box = ui.Container(ui.TextDisplay("No Wordle in the server meets the condition of having at least %i players" % at_least), accent_colour = discord.Colour.red())
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    await local_summary(interaction, mindate.isoformat(), pars_from_server)
    return

@tree.command(name = "par_line", description = "Line graph of pars from [start {default: oldest Wordle}] to [end {default: most recent Wordle}]")
@app_commands.describe(start = "format: YYYY-MM-DD", end = "format: YYYY-MM-DD")
async def par_line(interaction: discord.Interaction, start: str | None, end: str | None):
    await interaction.response.defer(ephemeral = True, thinking = True)
    calendar = servers[interaction.guild_id].calendar
    view = ui.LayoutView()
    try:
        start = dt.date.fromisoformat(start)
    except(ValueError, TypeError):
        if start == None:
            start = min(list(calendar.keys()))
        else:
            box = ui.Container(accent_colour = discord.Colour.magenta())
            box.add_item(ui.TextDisplay("Invalid start date"))
            view.add_item(box)
            await interaction.followup.send(view = view)
            return
    try:
        end = dt.date.fromisoformat(end)
    except(ValueError, TypeError):
        if end == None:
            end = max(list(calendar.keys()))
        else:
            box = ui.Container(accent_colour = discord.Colour.magenta())
            box.add_item(ui.TextDisplay("Invalid end date"))
            view.add_item(box)
            await interaction.followup.send(view = view)
            return
    data = []
    gdata = []
    for date in np.arange(start, end + dt.timedelta(days = 1)):
        date = dt.date.fromisoformat(str(date))
        if date in calendar:
            data += [calendar[date].par]
        else:
            data += [None]
        if date in servers[interaction.guild_id].sglobal:
            gdata += [servers[interaction.guild_id].sglobal[date]]
        else:
            data += [None]
    data = np.array(data)
    fig = plt.figure(figsize=(max(len(data) * 0.125, 8), 4.8))
    ax = fig.add_subplot()
    ax.plot(np.arange(start, end + dt.timedelta(days = 1)), data, label = "Server Pars")
    ax.scatter(np.arange(start, end + dt.timedelta(days = 1)), data)
    ax.plot(np.arange(start, end + dt.timedelta(days = 1)), gdata, label = "Global Pars")
    ax.set_ylabel("Par")
    ax.set_xlabel("Date")
    ax.legend()
    ax.yaxis.set_major_locator(ticker.MultipleLocator(1))
    ax.yaxis.set_minor_locator(ticker.MultipleLocator(0.2))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval = 7))
    ax.xaxis.set_minor_locator(mdates.DayLocator(interval = 1))
    ax.grid(visible = True, axis = 'both', which = 'major', lw = 2)
    ax.grid(visible = True, axis = 'both', which = 'minor', lw = 1)
    ax.tick_params(axis = 'x', labelrotation = 90)
    fig.savefig("par-overview.png", bbox_inches = "tight")
    await interaction.followup.send(file = discord.File("par-overview.png"))
    os.remove("par-overview.png")
    return

@tree.command(name = "set_base_loss_weight", description = "OWNER ONLY: Sets losses as a score of [x {default: 7.5}] / 6 for pars/averages")
async def set_base_loss_weight(interaction: discord.Interaction, x: int | None):
    await interaction.response.defer()
    wguild = servers[interaction.guild_id]
    view = ui.LayoutView()
    if interaction.user != wguild.owner:
        box = ui.Container(ui.TextDisplay("nuh uh uh"), accent_colour = discord.Colour.red())
        view.add_item(box)
        await interaction.followup.send(view = view)
        return
    if x == None:
        x = 7.5
    wguild.BASE_LOSS_WEIGHT = x
    box = ui.Container(ui.TextDisplay("Base loss weight set to %.2f / 6. Recalibrating database now." % np.round(x, decimals = 3)), accent_colour = discord.Colour.blurple())
    view.add_item(box)
    first = await interaction.followup.send(view = view)
    await prep_guild(interaction.guild)
    wguild.init_sglobal()
    box = ui.Container(ui.TextDisplay("Calibration complete. Commands now recognize the new base loss weight of %.2f." % np.round(x, decimals = 3)), accent_colour = discord.Colour.green())
    view.add_item(box)
    await interaction.followup.edit_message(first.id, view = view)
    return

TOKEN = os.environ['TOKEN']

app = Flask(__name__)

@app.route('/')
def heartbeat():
    return "<p>staying alive</p>"

def blood_circulator():
    app.run(host = '0.0.0.0', port = 4000)

def boot_bot():
    client.run(TOKEN)

t = threading.Thread(target = blood_circulator)
t.start()
time.sleep(10)
boot_bot()

